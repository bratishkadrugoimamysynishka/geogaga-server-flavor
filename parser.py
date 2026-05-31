import os
import urllib.request
import ipaddress
import collections
from concurrent.futures import ThreadPoolExecutor
import router_pb2

SOURCES = {
    "client-flavor-geosite": "https://github.com/bratishkadrugoimamysynishka/geogaga-client-flavor/raw/release/geosite.dat",
    "client-flavor-geoip": "https://github.com/bratishkadrugoimamysynishka/geogaga-client-flavor/raw/release/geoip.dat",
    "server-flavor-geosite": "https://github.com/bratishkadrugoimamysynishka/geogaga-server-flavor/raw/release/geosite.dat",
    "server-flavor-geoip": "https://github.com/bratishkadrugoimamysynishka/geogaga-server-flavor/raw/release/geoip.dat",
    "v2fly-geosite": "https://github.com/v2fly/domain-list-community/raw/release/dlc.dat",
    "Loyalsoldier-geoip": "https://github.com/Loyalsoldier/v2ray-rules-dat/raw/release/geoip.dat",
    "hydraponique-geosite": "https://github.com/hydraponique/roscomvpn-geosite/raw/release/geosite.dat",
    "hydraponique-geoip": "https://github.com/hydraponique/roscomvpn-geoip/raw/release/geoip.dat",
    "runetfreedom-geosite": "https://github.com/runetfreedom/russia-blocked-geosite/raw/release/geosite.dat",
    "runetfreedom-geoip": "https://github.com/runetfreedom/russia-blocked-geoip/raw/release/geoip.dat"
}

def get_domain_type_str(d_type):
    if d_type == 0: return "keyword"
    if d_type == 1: return "regexp"
    if d_type == 2: return "domain"
    if d_type == 3: return "full"
    return "unknown"

def format_domain(d):
    prefix = get_domain_type_str(d.type)
    return f"{prefix}:{d.value}" if prefix != "unknown" else d.value

def format_cidr(c):
    try:
        addr = ipaddress.ip_address(c.ip)
        return f"{addr}/{c.prefix}", "IPv4" if isinstance(addr, ipaddress.IPv4Address) else "IPv6"
    except Exception:
        return f"INVALID_IP/{c.prefix}", "invalid"

def process_single_source(folder_name, url):
    print(f"Starting: {folder_name}")
    os.makedirs(folder_name, exist_ok=True)
    
    # Скачивание файла
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            data = response.read()
    except Exception as e:
        print(f"❌ Failed to download {folder_name}: {e}")
        return

    is_geoip = "geoip" in folder_name.lower() or "geoip" in url.lower()
    
    try:
        if is_geoip:
            parsed_list = router_pb2.GeoIPList.FromString(data)
            attr_name = "cidr"
        else:
            parsed_list = router_pb2.GeoSiteList.FromString(data)
            attr_name = "domain"
    except Exception as e:
        print(f"❌ Failed to parse protobuf for {folder_name}: {e}")
        return

    total_elements = 0
    total_categories = len(parsed_list.entry)
    summary_lines = []
    
    # Словари для подсчета глобальных типов данных внутри текущего dat-файла
    global_type_counts = collections.Counter()

    for entry in parsed_list.entry:
        cat_name = entry.country_code
        safe_cat_name = "".join([c for c in cat_name if c.isalpha() or c.isdigit() or c in ('-', '_')]).rstrip()
        items = getattr(entry, attr_name)
        
        elements_count = len(items)
        total_elements += elements_count
        
        # Локальный подсчет типов для этой конкретной категории
        cat_type_counts = collections.Counter()
        lst_lines = []
        
        for item in items:
            if is_geoip:
                cidr_str, ip_type = format_cidr(item)
                lst_lines.append(cidr_str)
                cat_type_counts[ip_type] += 1
                global_type_counts[ip_type] += 1
            else:
                t_str = get_domain_type_str(item.type)
                lst_lines.append(format_domain(item))
                cat_type_counts[t_str] += 1
                global_type_counts[t_str] += 1

        # Формируем строку брейкдауна для категории
        type_details = ", ".join([f"{k}: {v}" for k, v in cat_type_counts.items()])
        summary_lines.append(f"- {cat_name}: {elements_count} items ({type_details})")
        
        # Запись .lst файла
        lst_path = os.path.join(folder_name, f"{safe_cat_name}.lst")
        with open(lst_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lst_lines) + "\n")

    # Формируем итоговый _summary.txt
    summary_path = os.path.join(folder_name, "_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"=== SUMMARY: {folder_name} ===\n")
        f.write(f"Total categories: {total_categories}\n")
        f.write(f"Total elements: {total_elements}\n\n")
        
        f.write("Total elements by data type:\n")
        for k, v in global_type_counts.items():
            f.write(f"  {k}: {v}\n")
        f.write("\n")
        
        f.write("Categories Breakdown:\n")
        f.write("\n".join(summary_lines) + "\n")
        
    print(f"✓ Finished: {folder_name}")

def parse_and_dump_parallel():
    # Запускаем параллельную обработку. max_workers=5 хватит за глаза, 
    # чтобы не упереться в лимиты гитхаба по числу одновременных запросов
    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(lambda item: process_single_source(*item), SOURCES.items())

if __name__ == "__main__":
    parse_and_dump_parallel()
    print("All parsing tasks completed.")
