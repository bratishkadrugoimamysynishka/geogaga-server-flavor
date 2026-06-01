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

def parse_json_cdn_source(data, allowed_cats_set):
    """
    Разбирает JSON структуру базы CDN, фильтрует провайдеров (регистронезависимо)
    и резолвит их автономии через RIPE Stat API.
    """
    all_asns = set()
    all_cidrs = set()

    for provider, info in data.items():
        if provider.upper() in allowed_cats_set:
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
        print(f"[JSON] Найдено {len(all_asns)} ASN для обработки. Резолв через RIPE...")
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

def download_and_parse(source, list_class):
    """Вынесено в отдельную функцию для параллельного выполнения в потоках"""
    print(f"Downloading: {source['url']}")
    try:
        req = urllib.request.Request(source['url'], headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
        
        # Динамическое определение типа контента по расширению
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
    
    # Качаем все апстримы параллельно (включая JSON-файлы)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(lambda src: download_and_parse(src, list_class), config)
        
    for source, parsed_data in results:
        if parsed_data is None:
            continue
            
        # Сценарий А: Обработка JSON-источника IP адресов
        if source['url'].lower().endswith('.json'):
            if attr_name != "cidr":
                # Пропускаем JSON-источники IP при сборке доменов (geosite)
                continue
                
            for rule in source['rules']:
                src_cats = {c.upper() for c in rule['src']}
                dst_cat = rule['dst'].upper()
                
                fetched_cidrs = parse_json_cdn_source(parsed_data, src_cats)
                category_items[dst_cat].extend(fetched_cidrs)
                print(f"[BUILDER] Интегрировано {len(fetched_cidrs)} IP префиксов в категорию {dst_cat} из JSON")
        
        # Сценарий Б: Стандартная обработка бинарного .dat файла
        else:
            for rule in source['rules']:
                src_cats = {c.upper() for c in rule['src']} # Set для моментального поиска O(1)
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

    # Запуск geosite и geoip последовательно, но внутри каждого — полная многопоточность сети
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
