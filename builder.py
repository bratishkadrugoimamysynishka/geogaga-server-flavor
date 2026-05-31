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

def download_and_parse(source, list_class):
    """Вынесено в отдельную функцию для параллельного выполнения в потоках"""
    print(f"Downloading: {source['url']}")
    try:
        req = urllib.request.Request(source['url'], headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
        parsed_list = list_class.FromString(data)
        return source, parsed_list
    except Exception as e:
        print(f"❌ Error downloading/parsing {source['url']}: {e}")
        return source, None

def process_dat(config, list_class, attr_name):
    category_items = collections.defaultdict(list)
    
    # Смена парадигмы: качаем все апстримы параллельно (максимум 4 потока)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(lambda src: download_and_parse(src, list_class), config)
        
    for source, parsed_list in results:
        if parsed_list is None:
            continue
            
        for rule in source['rules']:
            src_cats = {c.upper() for c in rule['src']} # Set для моментального поиска O(1)
            dst_cat = rule['dst'].upper()
            
            for entry in parsed_list.entry:
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
    with open(sys.argv[1], 'r') as f:
        config = json.load(f)

    # Запуск geosite и geoip последовательно, но внутри каждого — полная многопоточность сети
    if 'geosite' in config:
        geosite = process_dat(config['geosite'], router_pb2.GeoSiteList, "domain")
        with open("geosite.dat", "wb") as f: 
            f.write(geosite.SerializeToString())
        
    if 'geoip' in config:
        geoip = process_dat(config['geoip'], router_pb2.GeoIPList, "cidr")
        with open("geoip.dat", "wb") as f: 
            f.write(geoip.SerializeToString())
        
    print("Build completed successfully.")
