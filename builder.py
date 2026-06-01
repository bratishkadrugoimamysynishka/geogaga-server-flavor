import sys
import json
import urllib.request
import collections
import ipaddress
from concurrent.futures import ThreadPoolExecutor
import router_pb2

def optimize_domains(domains_list):
    dom_map = {}
    full_map = {}
    plains = []
    regexes = []
    others = []

    # 1. Быстрая группировка по типам
    for d in domains_list:
        if d.type == 0: 
            plains.append(d)
        elif d.type == 1: 
            regexes.append(d)
        elif d.type == 2:
            if d.value not in dom_map or len(d.attribute) > len(dom_map[d.value].attribute):
                dom_map[d.value] = d
        elif d.type == 3:
            if d.value not in full_map or len(d.attribute) > len(full_map[d.value].attribute):
                full_map[d.value] = d
        else:
            others.append(d)

    # Кэшируем значения plain-доменов для ускорения substring-поиска
    plain_values = [p.value for p in plains]

    final_doms = set()
    # Сортируем от коротких доменов к длинным (чтобы родительские зоны обрабатывались первыми)
    sorted_dom_keys = sorted(dom_map.keys(), key=len)
    
    for d_val in sorted_dom_keys:
        parts = d_val.split('.')
        # Оптимизация O(1) вместо O(N): проверяем существование родительского домена по Set
        is_subdomain = False
        for i in range(1, len(parts)):
            parent = '.'.join(parts[i:])
            if parent in final_doms:
                is_subdomain = True
                break
                
        if is_subdomain:
            continue

        # Быстрая проверка на вхождение keyword
        if any(p_val in d_val for p_val in plain_values):
            continue

        final_doms.add(d_val)

    final_fulls = set()
    for f_val in full_map.keys():
        parts = f_val.split('.')
        
        # Проверка перекрытия обычным Domain через Set-lookup
        is_covered_by_domain = False
        for i in range(len(parts)):
            parent = '.'.join(parts[i:])
            if parent in final_doms:
                is_covered_by_domain = True
                break
                
        if is_covered_by_domain:
            continue

        if any(p_val in f_val for p_val in plain_values):
            continue

        final_fulls.add(f_val)

    # 2. Сборка оригинальных объектов
    optimized = []
    optimized.extend(plains)
    optimized.extend(regexes)
    for d_val in final_doms: 
        optimized.append(dom_map[d_val])
    for f_val in final_fulls: 
        optimized.append(full_map[f_val])
    optimized.extend(others)
    
    return optimized

def optimize_ips(cidr_list):
    ipv4_nets = []
    ipv6_nets = []
    for c in cidr_list:
        try:
            addr = ipaddress.ip_address(c.ip)
            net = ipaddress.ip_network(f"{addr}/{c.prefix}", strict=False)
            if isinstance(net, ipaddress.IPv4Network): 
                ipv4_nets.append(net)
            else: 
                ipv6_nets.append(net)
        except Exception:
            pass
            
    opt_v4 = list(ipaddress.collapse_addresses(ipv4_nets))
    opt_v6 = list(ipaddress.collapse_addresses(ipv6_nets))

    optimized = []
    for net in opt_v4 + opt_v6:
        c = router_pb2.CIDR()
        c.ip = net.network_address.packed
        c.prefix = net.prefixlen
        optimized.append(c)
    return optimized

def parse_json_source_geoip(data, allowed_cats_set):
    """
    Разбирает JSON структуру базы CDN, фильтрует провайдеров (строго в верхнем регистре)
    и резолвит их автономии через RIPE Stat API.
    """
    all_asns = set()
    all_cidrs = set()

    for provider, info in data.items():
        if provider.upper() in allowed_cats_set:
            cidrs = info.get("cidrs", []) or info.get("ips", []) or []
            for c in cidrs:
                if isinstance(c, str) and '/' in c:
                    all_cidrs.add(c.strip())

            asns = info.get("asns", []) or []
            for asn in asns:
                if isinstance(asn, str):
                    asn_digits = "".join(filter(str.isdigit, asn))
                    if asn_digits:
                        all_asns.add(asn_digits)

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
            print(f"⚠️ Warning fetching AS{asn}: {e}")
        return prefixes

    if all_asns:
        print(f"[JSON-IP] Найдено {len(all_asns)} ASN для обработки. Резолв через RIPE...")
        with ThreadPoolExecutor(max_workers=15) as executor:
            for chunk in executor.map(fetch_asn, all_asns):
                all_cidrs.update(chunk)

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

def parse_json_source_geosite(data, allowed_cats_set):
    """
    Разбирает JSON структуру для Geosite. Категории приводятся к верхнему регистру.
    Поддерживает плоские списки строк с префиксами и объекты со списками по типам доменов.
    """
    proto_domains = []
    
    # Сопоставление строковых представлений с типами Protobuf
    type_mapping = {
        "plain": router_pb2.Domain.Plain,
        "keyword": router_pb2.Domain.Plain,
        "regex": router_pb2.Domain.Regex,
        "domain": router_pb2.Domain.Domain,
        "full": router_pb2.Domain.Full
    }

    for category, content in data.items():
        if category.upper() not in allowed_cats_set:
            continue
            
        # Вариант 1: Плоский список строк ["domain:google.com", "apple.com"]
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, str):
                    continue
                
                d_type = router_pb2.Domain.Domain  # Тип по умолчанию, если префикс отсутствует
                d_value = item.strip()
                
                if ":" in d_value:
                    prefix, value = d_value.split(":", 1)
                    if prefix.lower() in type_mapping:
                        d_type = type_mapping[prefix.lower()]
                        d_value = value.strip()
                
                if d_value:
                    d_proto = router_pb2.Domain()
                    d_proto.type = d_type
                    d_proto.value = d_value
                    proto_domains.append(d_proto)
                    
        # Вариант 2: Объект со списками по типам {"domain": ["google.com"], "regex": [".*"]}
        elif isinstance(content, dict):
            for t_key, v_list in content.items():
                if t_key.lower() in type_mapping and isinstance(v_list, list):
                    d_type = type_mapping[t_key.lower()]
                    for item in v_list:
                        if isinstance(item, str) and item.strip():
                            d_proto = router_pb2.Domain()
                            d_proto.type = d_type
                            d_proto.value = item.strip()
                            proto_domains.append(d_proto)
                            
    return proto_domains

def download_and_parse(source, list_class):
    print(f"Downloading: {source['url']}")
    try:
        req = urllib.request.Request(source['url'], headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
        
        if source['url'].lower().endswith('.json'):
            return source, json.loads(data.decode('utf-8'))
        else:
            parsed_list = list_class.FromString(data)
            return source, parsed_list
    except Exception as e:
        print(f"❌ Error downloading/parsing {source['url']}: {e}")
        return source, None

def process_dat(config, list_class, attr_name):
    category_items = collections.defaultdict(list)
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(lambda src: download_and_parse(src, list_class), config)
        
    for source, parsed_data in results:
        if parsed_data is None:
            continue
            
        if source['url'].lower().endswith('.json'):
            for rule in source['rules']:
                src_cats = {c.upper() for c in rule['src']}
                dst_cat = rule['dst'].upper()
                
                if attr_name == "cidr":
                    fetched_cidrs = parse_json_source_geoip(parsed_data, src_cats)
                    category_items[dst_cat].extend(fetched_cidrs)
                    print(f"[BUILDER] Интегрировано {len(fetched_cidrs)} IP префиксов в категорию {dst_cat} из JSON")
                elif attr_name == "domain":
                    fetched_domains = parse_json_source_geosite(parsed_data, src_cats)
                    category_items[dst_cat].extend(fetched_domains)
                    print(f"[BUILDER] Интегрировано {len(fetched_domains)} доменов в категорию {dst_cat} из JSON")
        
        else:
            for rule in source['rules']:
                src_cats = {c.upper() for c in rule['src']}
                dst_cat = rule['dst'].upper()
                
                for entry in parsed_data.entry:
                    current_cat = entry.country_code.upper()
                    if "*" in src_cats or current_cat in src_cats:
                        target = current_cat if dst_cat == "*" else dst_cat
                        items = getattr(entry, attr_name)
                        category_items[target].extend(items)
                    
    out_list = list_class()
    for cat, items in category_items.items():
        entry = out_list.entry.add()
        entry.country_code = cat.upper() 
        target_list = getattr(entry, attr_name)
        
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
        
    print("Build completed successfully.")
