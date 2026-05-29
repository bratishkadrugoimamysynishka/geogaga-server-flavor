import sys
import os
import requests
import ipaddress
from grpc_tools import protoc

# 1. Формируем структуру Protobuf файлов для V2Ray/Xray
proto_content = """
syntax = "proto3";
package v2ray.core.app.router;

message CIDR {
  bytes ip = 1;
  uint32 prefix = 2;
}
message GeoIP {
  string country_code = 1;
  repeated CIDR cidr = 2;
}
message GeoIPList {
  repeated GeoIP entry = 1;
}

message Domain {
  enum Type {
    Plain = 0;
    Regex = 1;
    Domain = 2;
    Full = 3;
  }
  Type type = 1;
  string value = 2;
  message Attribute {
    string key = 1;
    oneof value {
      bool bool_value = 2;
      int64 int_value = 3;
    }
  }
  repeated Attribute attribute = 3;
}
message SiteGroup {
  string category = 1;
  repeated Domain domain = 2;
}
message SiteList {
  repeated SiteGroup entry = 1;
}
"""

with open("router.proto", "w") as f:
    f.write(proto_content)

# Компилируем proto-структуру в Python модули
protoc.main(('', '-I.', '--python_out=.', 'router.proto'))
sys.path.append(os.getcwd())
import router_pb2

def download_file(url):
    r = requests.get(url)
    r.raise_for_status()
    return r.content

def optimize_single_geoip_entry(entry):
    networks_v4 = []
    networks_v6 = []
    
    for cidr in entry.cidr:
        ip_bytes = cidr.ip
        prefix = cidr.prefix
        if len(ip_bytes) == 4:
            ip_str = ipaddress.IPv4Address(ip_bytes)
            networks_v4.append(ipaddress.ip_network(f"{ip_str}/{prefix}", strict=False))
        elif len(ip_bytes) == 16:
            ip_str = ipaddress.IPv6Address(ip_bytes)
            networks_v6.append(ipaddress.ip_network(f"{ip_str}/{prefix}", strict=False))
        else:
            continue
    
    # Схлопываем IPv4 и IPv6 строго раздельно, чтобы не поймать TypeError
    collapsed_v4 = list(ipaddress.collapse_addresses(networks_v4))
    collapsed_v6 = list(ipaddress.collapse_addresses(networks_v6))
    
    # Записываем оптимизированные подсети обратно
    del entry.cidr[:]
    
    for net in collapsed_v4:
        cidr = entry.cidr.add()
        cidr.ip = net.network_address.packed
        cidr.prefix = net.prefixlen
        
    for net in collapsed_v6:
        cidr = entry.cidr.add()
        cidr.ip = net.network_address.packed
        cidr.prefix = net.prefixlen

def optimize_single_geosite_entry(entry):
    domains_set = set()
    full_set = set()
    plain_set = set()
    regex_set = set()
    
    for d in entry.domain:
        val = d.value.lower().strip()
        if d.type == 2:
            domains_set.add(val)
        elif d.type == 3:
            full_set.add(val)
        elif d.type == 0:
            plain_set.add(val)
        elif d.type == 1:
            regex_set.add(val)

    # Убираем поддомены через иерархический хеш-сет
    sorted_domains = sorted(list(domains_set), key=lambda x: (x.count('.'), len(x)))
    optimized_domains = []
    parent_registry = set()
    
    for d_dom in sorted_domains:
        parts = d_dom.split('.')
        is_subdomain = False
        for i in range(len(parts) - 1, 0, -1):
            parent_candidate = '.'.join(parts[i:])
            if parent_candidate in parent_registry:
                is_subdomain = True
                break
        if not is_subdomain:
            optimized_domains.append(d_dom)
            parent_registry.add(d_dom)

    # Проверка Full-доменов по родительскому дереву
    optimized_full = set()
    for f_dom in full_set:
        parts = f_dom.split('.')
        covered = False
        for i in range(len(parts)):
            candidate = '.'.join(parts[i:])
            if candidate in parent_registry:
                covered = True
                break
        if not covered:
            optimized_full.add(f_dom)

    del entry.domain[:]
    for val in optimized_domains:
        d = entry.domain.add()
        d.type = 2
        d.value = val
    for val in optimized_full:
        d = entry.domain.add()
        d.type = 3
        d.value = val
    for val in plain_set:
        d = entry.domain.add()
        d.type = 0
        d.value = val
    for val in regex_set:
        d = entry.domain.add()
        d.type = 1
        d.value = val

# ==========================================
# --- СБОРКА GEOSITE ---
# ==========================================
print("Processing GeoSite (Server)...")
geosite_output = router_pb2.SiteList()

# Создаем объединенную категорию для сервера
server_site_proxy = geosite_output.entry.add()
server_site_proxy.category = "GEOGAGA-PROXY"

# 1. Загружаем hydraponique/roscomvpn-geosite
hydra_site_data = download_file("https://github.com/hydraponique/roscomvpn-geosite/raw/release/geosite.dat")
hydra_site = router_pb2.SiteList()
hydra_site.ParseFromString(hydra_site_data)

# Для сервера в прокси-режим идут категории, которые на клиенте были DIRECT
hydra_server_proxy_cats = {"whitelist", "category-ru", "torrent", "apple", "microsoft", "twitch", "pinterest", "steam", "epicgames", "riot", "escapefromtarkov", "faceit", "private"}

for entry in hydra_site.entry:
    if entry.category.lower() in hydra_server_proxy_cats:
        server_site_proxy.domain.extend(entry.domain)

# 2. Загружаем runetfreedom/russia-blocked-geosite
rf_site_data = download_file("https://github.com/runetfreedom/russia-blocked-geosite/raw/release/geosite.dat")
rf_site = router_pb2.SiteList()
rf_site.ParseFromString(rf_site_data)

rf_server_proxy_cats = {"ru-blocked"}

for entry in rf_site.entry:
    if entry.category.lower() in rf_server_proxy_cats:
        server_site_proxy.domain.extend(entry.domain)

print("Optimizing custom Server GEOGAGA Geosite category...")
optimize_single_geosite_entry(server_site_proxy)

# ==========================================
# --- СБОРКА GEOIP ---
# ==========================================
print("Processing GeoIP (Server)...")
geoip_output = router_pb2.GeoIPList()

server_ip_proxy = geoip_output.entry.add()
server_ip_proxy.country_code = "GEOGAGA-PROXY"

# 1. Загружаем runetfreedom/russia-blocked-geoip
rf_ip_data = download_file("https://github.com/runetfreedom/russia-blocked-geoip/raw/release/geoip.dat")
rf_ip = router_pb2.GeoIPList()
rf_ip.ParseFromString(rf_ip_data)
rf_ip_server_proxy = {"ru-blocked-community", "re-filter"}

for entry in rf_ip.entry:
    if entry.country_code.lower() in rf_ip_server_proxy:
        server_ip_proxy.cidr.extend(entry.cidr)

# 2. Загружаем DanielLavrushin/b4geoip
b4_ip_data = download_file("https://github.com/DanielLavrushin/b4geoip/releases/latest/download/geoip.dat")
b4_ip = router_pb2.GeoIPList()
b4_ip.ParseFromString(b4_ip_data)
b4_server_proxy = {"aeza", "akamai", "amazon", "belcloud", "buyvm", "cdn77", "cloudflare", "cogent", "constant", "contabo", "datacamp", "digitalocean", "digitalone", "fastly", "gcore", "glesys", "gthost", "hetzner", "meganz", "melbicom", "oracle", "ovh", "scalaxy", "scaleway", "zerocdn"}

for entry in b4_ip.entry:
    if entry.country_code.lower() in b4_server_proxy:
        server_ip_proxy.cidr.extend(entry.cidr)

# 3. Загружаем hydraponique/roscomvpn-geoip (для сервера эти подсети становятся частью проксирования)
hydra_ip_data = download_file("https://github.com/hydraponique/roscomvpn-geoip/raw/release/geoip.dat")
hydra_ip = router_pb2.GeoIPList()
hydra_ip.ParseFromString(hydra_ip_data)
hydra_server_proxy = {"direct", "whitelist", "private"}

for entry in hydra_ip.entry:
    if entry.country_code.lower() in hydra_server_proxy:
        server_ip_proxy.cidr.extend(entry.cidr)

print("Optimizing custom Server GEOGAGA GeoIP category...")
optimize_single_geoip_entry(server_ip_proxy)

# СТРОГОЕ ПРИВЕДЕНИЕ К UPPERCASE
for entry in geosite_output.entry:
    entry.category = entry.category.upper()
for entry in geoip_output.entry:
    entry.country_code = entry.country_code.upper()

# Сохранение готовых файлов
with open("geosite.dat", "wb") as f:
    f.write(geosite_output.SerializeToString())

with open("geoip.dat", "wb") as f:
    f.write(geoip_output.SerializeToString())

print("Server files optimized and compiled successfully.")
