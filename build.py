import sys
import json
import urllib.request
import collections
import ipaddress
import router_pb2

def optimize_domains(domains_list):
    dom_map = {}
    full_map = {}
    plains = []
    regexes = []
    others = []

    # 1. Группируем домены по типам (Plain=0, Regex=1, Domain=2, Full=3)
    for d in domains_list:
        if d.type == 0: 
            plains.append(d)
        elif d.type == 1: 
            regexes.append(d)
        elif d.type == 2:
            # Сохраняем объект целиком, чтобы не потерять router_pb2.Domain.Attribute
            # При дубликатах отдаем приоритет объекту с бОльшим количеством атрибутов
            if d.value not in dom_map or len(d.attribute) > len(dom_map[d.value].attribute):
                dom_map[d.value] = d
        elif d.type == 3:
            if d.value not in full_map or len(d.attribute) > len(full_map[d.value].attribute):
                full_map[d.value] = d
        else:
            others.append(d)

    final_doms = set()
    # Сортируем Domain по длине для проверки родительских доменов
    sorted_dom_keys = sorted(dom_map.keys(), key=len)
    for d_val in sorted_dom_keys:
        parts = d_val.split('.')
        # Отбрасываем, если родительский домен уже в списке
        is_subdomain = any('.'.join(parts[i:]) in final_doms for i in range(len(parts)))
        # Отбрасываем, если домен покрывается правилом Plain (Keyword подстрокой)
        has_keyword = any(p.value in d_val for p in plains)
        
        if not is_subdomain and not has_keyword:
            final_doms.add(d_val)

    final_fulls = set()
    for f_val in full_map.keys():
        parts = f_val.split('.')
        # Отбрасываем Full, если он перекрывается обычным Domain или Plain
        is_covered_by_domain = any('.'.join(parts[i:]) in final_doms for i in range(len(parts)))
        has_keyword = any(p.value in f_val for p in plains)
        
        if not is_covered_by_domain and not has_keyword:
            final_fulls.add(f_val)

    # 2. Сборка оптимизированного списка оригинальных объектов
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
            # Извлекаем IP из packed bytes
            addr = ipaddress.ip_address(c.ip)
            net = ipaddress.ip_network(f"{addr}/{c.prefix}", strict=False)
            if isinstance(net, ipaddress.IPv4Network): 
                ipv4_nets.append(net)
            else: 
                ipv6_nets.append(net)
        except Exception:
            pass
            
    # collapse_addresses схлопывает пересечения, включения и дубли внутри v4 и v6 раздельно
    opt_v4 = list(ipaddress.collapse_addresses(ipv4_nets))
    opt_v6 = list(ipaddress.collapse_addresses(ipv6_nets))

    optimized = []
    for net in opt_v4 + opt_v6:
        c = router_pb2.CIDR()
        c.ip = net.network_address.packed
        c.prefix = net.prefixlen
        optimized.append(c)
    return optimized

def process_dat(config, list_class, attr_name):
    category_items = collections.defaultdict(list)
    
    for source in config:
        print(f"Downloading: {source['url']}")
        req = urllib.request.Request(source['url'], headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = response.read()
            
        parsed_list = list_class.FromString(data)
        
        for rule in source['rules']:
            src_cats = [c.upper() for c in rule['src']]
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
        # Принудительный апперкейс для всех итоговых категорий
        entry.country_code = cat.upper() 
        target_list = getattr(entry, attr_name)
        
        if cat.upper().startswith("GEOGAGA-"):
            optimized_items = optimize_domains(items) if attr_name == "domain" else optimize_ips(items)
            target_list.extend(optimized_items)
        else:
            # Для сторонних категорий (когда правило src: "*", dst: "*") 
            # удаляем только полные дубликаты байткода, чтобы не ломать чужую логику
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

    if 'geosite' in config:
        geosite = process_dat(config['geosite'], router_pb2.GeoSiteList, "domain")
        with open("geosite.dat", "wb") as f: 
            f.write(geosite.SerializeToString())
        
    if 'geoip' in config:
        geoip = process_dat(config['geoip'], router_pb2.GeoIPList, "cidr")
        with open("geoip.dat", "wb") as f: 
            f.write(geoip.SerializeToString())
        
    print("Build completed successfully.")
