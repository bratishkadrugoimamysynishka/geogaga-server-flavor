import sys
import os
import requests
import ipaddress
from grpc_tools import protoc

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

with open("router.proto", "w", encoding="utf-8") as f:
    f.write(proto_content)

protoc.main(('', '-I.', '--python_out=.', 'router.proto'))
sys.path.append(os.getcwd())
import router_pb2

def download_file(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content

def optimize_domain_list(domain_list):
    domains = [d for d in domain_list if d.type == 2]
    fulls = [d for d in domain_list if d.type == 3]
    plains = [d for d in domain_list if d.type == 0]
    regexes = [d for d in domain_list if d.type == 1]
    
    domains.sort(key=lambda x: len(x.value.lower().split('.')))
    valid_domains = set()
    optimized_domains = []
    
    for d in domains:
        val = d.value.lower()
        if val in valid_domains:
            continue
        parts = val.split('.')
        is_redundant = False
        for i in range(1, len(parts)):
            parent = '.'.join(parts[i:])
            if parent in valid_domains:
                is_redundant = True
                break
        if not is_redundant:
            valid_domains.add(val)
            optimized_domains.append(d)
            
    valid_fulls = set()
    optimized_fulls = []
    for f in fulls:
        val = f.value.lower()
        if val in valid_fulls:
            continue
        parts = val.split('.')
        is_covered = False
        for i in range(len(parts)):
            parent = '.'.join(parts[i:])
            if parent in valid_domains:
                is_covered = True
                break
        if not is_covered:
            valid_fulls.add(val)
            optimized_fulls.append(f)
            
    seen_plains = set()
    optimized_plains = []
    for p in plains:
        if p.value not in seen_plains:
            seen_plains.add(p.value)
            optimized_plains.append(p)
            
    seen_regex = set()
    optimized_regex = []
    for r in regexes:
        if r.value not in seen_regex:
            seen_regex.add(r.value)
            optimized_regex.append(r)
            
    return optimized_domains + optimized_fulls + optimized_plains + optimized_regex

def optimize_cidr_list(cidr_list):
    v4_nets = []
    v6_nets = []
    for cidr in cidr_list:
        try:
            ip_obj = ipaddress.ip_address(cidr.ip)
            net = ipaddress.ip_network(f"{ip_obj}/{cidr.prefix}", strict=False)
            if net.version == 4:
                v4_nets.append(net)
            else:
                v6_nets.append(net)
        except Exception:
            continue
            
    collapsed = list(ipaddress.collapse_addresses(v4_nets)) + list(ipaddress.collapse_addresses(v6_nets))
    
    optimized_cidrs = []
    for net in collapsed:
        c = router_pb2.CIDR()
        c.ip = net.network_address.packed
        c.prefix = net.prefixlen
        optimized_cidrs.append(c)
    return optimized_cidrs

def main():
    geogaga_sites = {"GEOGAGA-BLOCK": [], "GEOGAGA-PROXY": []}
    geogaga_ips = {"GEOGAGA-BLOCK": [], "GEOGAGA-PROXY": []}
    other_sites = {}
    other_ips = {}

    print("Парсинг ресурсов для Flavor 2...")

    # --- GEOSITE СБОРКА ---
    # Источник 1
    url = "https://github.com/hydraponique/roscomvpn-geosite/raw/release/geosite.dat"
    s_list = router_pb2.SiteList()
    s_list.ParseFromString(download_file(url))
    for entry in s_list.entry:
        cat = entry.category.lower()
        if cat in {"whitelist", "category-ru"}:
            geogaga_sites["GEOGAGA-PROXY"].extend(entry.domain)
        elif cat in {"torrent", "private", "category-ads"}:
            geogaga_sites["GEOGAGA-BLOCK"].extend(entry.domain)

    # Источник 2
    url = "https://github.com/runetfreedom/russia-blocked-geosite/raw/release/geosite.dat"
    s_list = router_pb2.SiteList()
    s_list.ParseFromString(download_file(url))
    for entry in s_list.entry:
        cat = entry.category.lower()
        if cat in {"category-ads-all", "geosite:win-spy"}:
            geogaga_sites["GEOGAGA-BLOCK"].extend(entry.domain)

    # Источник 3 (Перенос AS-IS с принудительным апперкейсом категорий)
    url = "https://github.com/v2fly/domain-list-community/raw/release/dlc.dat"
    s_list = router_pb2.SiteList()
    s_list.ParseFromString(download_file(url))
    for entry in s_list.entry:
        cat_upper = entry.category.upper()
        if cat_upper not in other_sites:
            other_sites[cat_upper] = []
        other_sites[cat_upper].extend(entry.domain)

    # --- GEOIP СБОРКА ---
    # Источник 1
    url = "https://github.com/hydraponique/roscomvpn-geoip/raw/release/geoip.dat"
    g_list = router_pb2.GeoIPList()
    g_list.ParseFromString(download_file(url))
    for entry in g_list.entry:
        cat = entry.country_code.lower()
        if cat in {"direct", "whitelist"}:
            geogaga_ips["GEOGAGA-PROXY"].extend(entry.cidr)
        elif cat == "private":
            geogaga_ips["GEOGAGA-BLOCK"].extend(entry.cidr)

    # Источник 2 (Перенос AS-IS с принудительным апперкейсом категорий)
    url = "https://github.com/Loyalsoldier/v2ray-rules-dat/raw/release/geoip.dat"
    g_list = router_pb2.GeoIPList()
    g_list.ParseFromString(download_file(url))
    for entry in g_list.entry:
        cat_upper = entry.country_code.upper()
        if cat_upper not in other_ips:
            other_ips[cat_upper] = []
        other_ips[cat_upper].extend(entry.cidr)

    # --- ЗАПИСЬ И ОПТИМИЗАЦИЯ ФАЙЛОВ ---
    final_geosite = router_pb2.SiteList()
    
    # Оптимизируем только geogaga-*
    for cat, domains in geogaga_sites.items():
        if domains:
            entry = final_geosite.entry.add()
            entry.category = cat.upper()
            optimized = optimize_domain_list(domains)
            for d in optimized:
                entry.domain.add().CopyFrom(d)
                
    # Сторонние категории пишем as-is, но приводим название к верхнему регистру
    for cat, domains in other_sites.items():
        if domains:
            entry = final_geosite.entry.add()
            entry.category = cat
            for d in domains:
                entry.domain.add().CopyFrom(d)

    with open("geosite.dat", "wb") as f:
        f.write(final_geosite.SerializeToString())

    final_geoip = router_pb2.GeoIPList()
    
    # Оптимизируем только geogaga-*
    for cat, cidrs in geogaga_ips.items():
        if cidrs:
            entry = final_geoip.entry.add()
            entry.country_code = cat.upper()
            optimized = optimize_cidr_list(cidrs)
            for c in optimized:
                entry.cidr.add().CopyFrom(c)
                
    # Сторонние категории пишем as-is, но приводим название к верхнему регистру
    for cat, cidrs in other_ips.items():
        if cidrs:
            entry = final_geoip.entry.add()
            entry.country_code = cat
            for c in cidrs:
                entry.cidr.add().CopyFrom(c)

    with open("geoip.dat", "wb") as f:
        f.write(final_geoip.SerializeToString())

    print("Flavor 2 успешно собран и оптимизирован.")

if __name__ == "__main__":
    main()
