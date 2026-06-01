import sys
import json
import urllib.request
import collections
import ipaddress
from concurrent.futures import ThreadPoolExecutor
import router_pb2

def parse_json_cdn_source(url, allowed_categories):
    """
    Загружает resolved_ips.json, фильтрует провайдеров на основе списка src
    и резолвит их ASN через RIPE Stat API.
    """
    print(f"[BUILDER] Скачивание и парсинг JSON источника: {url}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"[BUILDER] Ошибка загрузки JSON источника {url}: {e}")
        return []

    all_asns = set()
    all_cidrs = set()
    allowed_cats = set(allowed_categories)

    for provider, info in data.items():
        if provider in allowed_cats:
            # Сбор прямых подсетей из файла
            cidrs = info.get("cidrs", []) or info.get("ips", []) or []
            for c in cidrs:
                if isinstance(c, str) and '/' in c:
                    all_cidrs.add(c.strip())

            # Сбор номеров автономных систем
            asns = info.get("asns", []) or []
            for asn in asns:
                if isinstance(asn, str):
                    asn_digits = "".join(filter(str.isdigit, asn))
                    if asn_digits:
                        all_asns.add(asn_digits)

    # Функция параллельного запроса префиксов автономной системы
    def fetch_asn(asn):
        prefixes = []
        asn_url = f"https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS{asn}"
        try:
            req = urllib.request.Request(asn_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_data = json.loads(resp.read().decode('utf-8'))
                for item in res_data.get("data", {}).get("prefixes", []):
                    p = item.get("prefix")
                    if p:
                        prefixes.append(p)
        except Exception as e:
            print(f"[BUILDER] Предупреждение по AS{asn}: {e}")
        return prefixes

    if all_asns:
        print(f"[BUILDER] Найдено {len(all_asns)} ASN для обработки. Запуск потоков...")
        with ThreadPoolExecutor(max_workers=15) as executor:
            for chunk in executor.map(fetch_asn, all_asns):
                all_cidrs.update(chunk)

    # Конвертация собранных CIDR подсетей в Protobuf объекты
    proto_cidrs = []
    for c_str in all_cidrs:
        try:
            net = ipaddress.ip_network(c_str, strict=False)
            cidr_proto = router_pb2.CIDR()
            cidr_proto.ip = net.network_address.packed
            cidr_proto.prefix = net.prefixlen
            proto_cidrs.append(cidr_proto)
        except Exception:
            continue

    return proto_cidrs


def optimize_domains(domains_list):
    # Ваш существующий код оптимизации доменов (без изменений)
    dom_map = {}
    full_map = {}
    plains = []
    regexes = []
    others = []
    for d in domains_list:
        if d.type == 0: plains.append(d)
        elif d.type == 1: regexes.append(d)
        elif d.type == 2:
            if d.value not in dom_map or len(d.attribute) > len(dom_map[d.value].attribute):
                dom_map[d.value] = d
        elif d.type == 3:
            if d.value not in full_map or len(d.attribute) > len(full_map[d.value].attribute):
                full_map[d.value] = d
        else: others.append(d)
    
    final_doms = set()
    sorted_dom_keys = sorted(dom_map.keys(), key=len)
    for d_val in sorted_dom_keys:
        parts = d_val.split('.')
        is_sub = False
        for i in range(1, len(parts)):
            parent = '.'.join(parts[i:])
            if parent in final_doms:
                is_sub = True
                break
        if not is_sub:
            final_doms.add(d_val)
            
    ret = []
    for d_val in final_doms: ret.append(dom_map[d_val])
    for f_val in full_map:
        parts = f_val.split('.')
        is_sub = False
        for i in range(1, len(parts)):
            parent = '.'.join(parts[i:])
            if parent in final_doms:
                is_sub = True
                break
        if not is_sub: ret.append(full_map[f_val])
    ret.extend(plains)
    ret.extend(regexes)
    ret.extend(others)
    return ret


def optimize_ips(ips_list):
    # Ваш существующий код оптимизации IP подсетей (без изменений)
    v4_nets = []
    v6_nets = []
    for c in ips_list:
        try:
            ip_obj = ipaddress.ip_address(c.ip)
            net = ipaddress.ip_network(f"{ip_obj}/{c.prefix}", strict=False)
            if net.version == 4: v4_nets.append(net)
            else: v6_nets.append(net)
        except Exception:
            continue
            
    v4_collapsed = list(ipaddress.collapse_addresses(v4_nets))
    v6_collapsed = list(ipaddress.collapse_addresses(v6_nets))
    
    ret = []
    for net in v4_collapsed + v6_collapsed:
        cidr_proto = router_pb2.CIDR()
        cidr_proto.ip = net.network_address.packed
        cidr_proto.prefix = net.prefixlen
        ret.append(cidr_proto)
    return ret


def process_dat(config_section, list_class, attr_name):
    category_items = collections.defaultdict(list)
    
    for entry in config_section:
        url = entry.get("url")
        if not url:
            continue
            
        rules = entry.get("rules", [])
        if not rules:
            continue

        # ДИНАМИЧЕСКИЙ ОПРЕДЕЛИТЕЛЬ ФОРМАТА: Если URL ведет на JSON файл
        if url.lower().endswith('.json'):
            if attr_name != "cidr":
                # Пропускаем JSON-источники IP при сборке доменов (geosite)
                continue
                
            for rule in rules:
                src_cats = rule.get("src", [])
                dst_cat = rule.get("dst", "").upper()
                if not dst_cat:
                    continue
                
                # Собираем данные из JSON по белому списку категорий (src)
                fetched_cidrs = parse_json_cdn_source(url, src_cats)
                category_items[dst_cat].extend(fetched_cidrs)
                print(f"[BUILDER] Успешно добавлено {len(fetched_cidrs)} IP/ASN префиксов в категорию {dst_cat}")
        
        # СТАНДАРТНЫЙ ОПРЕДЕЛИТЕЛЬ ФОРМАТА: Базовые бинарные .dat файлы
        else:
            print(f"[BUILDER] Скачивание базового dat-файла: {url}")
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=60) as response:
                    dat_data = response.read()
            except Exception as e:
                print(f"[BUILDER] Ошибка скачивания базового файла {url}: {e}")
                continue

            in_list = list_class()
            try:
                in_list.ParseFromString(dat_data)
            except Exception as e:
                print(f"[BUILDER] Ошибка десериализации данных из {url}: {e}")
                continue

            for rule in rules:
                src_cats = rule.get("src", [])
                dst_cat = rule.get("dst", "").upper()
                
                for entry_item in in_list.entry:
                    current_cat = entry_item.country_code.upper()
                    if current_cat in src_cats:
                        target = current_cat if dst_cat == "*" else dst_cat
                        items = getattr(entry_item, attr_name)
                        category_items[target].extend(items)
                        
    # Генерация выходной структуры и запуск оптимизации
    out_list = list_class()
    for cat, items in category_items.items():
        entry_out = out_list.entry.add()
        # Категории гарантированно пишутся большими буквами
        entry_out.country_code = cat.upper() 
        target_list = getattr(entry_out, attr_name)
        
        if cat.upper().startswith("GEOGAGA-"):
            optimized_items = optimize_domains(items) if attr_name == "domain" else optimize_ips(items)
            target_list.extend(optimized_items)
        else:
            seen = set()
            for item in items:
                s = item.SerializeToString()
                if s not in seen:
                    seen.add(s)
                    target_list.append(item)
                    
    return out_list

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python builder.py config.json")
        sys.exit(1)
        
    with open(sys.argv[1], 'r') as f:
        config = json.load(f)

    if 'geosite' in config:
        geosite = process_dat(config['geosite'], router_pb2.GeoSiteList, "domain")
        with open("geosite.dat", "wb") as f: 
            f.write(geosite.SerializeToString())
        print("[SUCCESS] Файл geosite.dat успешно сгенерирован.")
        
    if 'geoip' in config:
        geoip = process_dat(config['geoip'], router_pb2.GeoIPList, "cidr")
        with open("geoip.dat", "wb") as f: 
            f.write(geoip.SerializeToString())
        print("[SUCCESS] Файл geoip.dat успешно сгенерирован.")
