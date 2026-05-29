<p align="center">
  <img src="banner.svg" alt="GeoGaga - Server Flavor Banner" width="100%">
</p>

# GeoGaga — Server Flavor

**GeoGaga - Server Flavor** — это автоматически собираемые файлы данных `geoip.dat` и `geosite.dat`, специально оптимизированные для настройки умной **серверной** маршрутизации трафика. Сборка предназначена для использования непосредственно на стороне заграничного VPS-сервера под управлением Xray / Sing-box (в связке с панелями управления **3x-ui**, **Remnawave**, **Marzban** и др.).

Главная особенность данной серверной версии — агрегация, очистка от дубликатов и перепаковка специфичных категорий в кастомные группы правил с префиксом `GEOGAGA-`. Это позволяет эффективно отсекать мусорный трафик, маскировать запросы к заблокированным хостингам и хостить классические правила для полноценной работы сервера.

---

## 🛠 Рекомендуемый порядок правил на сервере

Для достижения максимального быстродействия, экономии трафика VPS и правильной логики распределения ресурсов рекомендуется выстраивать правила маршрутизации в следующем порядке:

1. **Блокировка (`Block`)** ➡️ Реклама, телеметрия ОС, трекеры и тяжелый торрент-трафик. Соединение сбрасывается моментально (`blackhole`).
2. **Маскировка (`Proxy`)** ➡️ Ресурсы, требующие обхода (через Cloudflare WARP или другой апстрим).
3. **Напрямую (`Direct`)** ➡️ Финальное правило (По умолчанию). Весь остальной трафик идет через основной интерфейс сервера.

### Пример структуры в конфигурации Xray JSON:
```json
"routing": {
  "domainStrategy": "AsIs",
  "rules": [
    {
      "type": "field",
      "outboundTag": "block",
      "domain": ["geosite:GEOGAGA-BLOCK"],
      "ip": ["geoip:GEOGAGA-BLOCK"]
    },
    {
      "type": "field",
      "outboundTag": "warp",
      "domain": ["geosite:GEOGAGA-PROXY"],
      "ip": ["geoip:GEOGAGA-PROXY"]
    },
    {
      "type": "field",
      "outboundTag": "direct",
      "network": "tcp,udp"
    }
  ]
}
```

---

## 📦 Описание категорий GeoSite (`geosite.dat`)

Категория `geosite.dat` содержит доменные имена, распределенные по целевым группам:

### 🚫 `geosite:geogaga-block`
Предназначена для жесткой блокировки ненужного трафика прямо на сервере.
* **Включает в себя категории:**
  * Из репозитория *hydraponique/roscomvpn-geosite*:
    * `torrent`, `private`, `category-ads` — торренты, приватные сети и рекламные домены.
  * Из репозитория *runetfreedom/russia-blocked-geosite*:
    * `category-ads-all`, `win-spy` — расширенная реклама и телеметрия Windows.

### 🔵 `geosite:geogaga-proxy`
Список доменов для маскировки (например, через Cloudflare WARP).
* **Включает в себя категории:**
  * Из репозитория *hydraponique/roscomvpn-geosite*:
    * `whitelist`, `category-ru` — списки доменов общего обхода.

### 🌐 Оригинальные теги (Добавлено as-is)
* Полная база доменов из репозитория **v2fly/domain-list-community**. Все категории (google, netflix, github и т.д.) импортируются без изменений для создания классических правил.

---

## 🌐 Описание категорий GeoIP (`geoip.dat`)

Категория `geoip.dat` оперирует массивами IP-адресов.

### 🚫 `geoip:geogaga-block`
Сетевые диапазоны для моментального сброса на внешнем интерфейсе сервера.
* **Включает в себя категории:**
  * Из репозитория *hydraponique/roscomvpn-geoip*:
    * `private` — диапазоны частных адресов (RFC 1918) для сетевой фильтрации.

### 🔵 `geoip:geogaga-proxy`
Сетевые диапазоны, перенаправляемые в интерфейс маскировки трафика.
* **Включает в себя категории:**
  * Из репозитория *hydraponique/roscomvpn-geoip*:
    * `direct`, `whitelist` — доверенные IP-адреса и подсети для обработки через апстрим.

### 🌐 Оригинальные теги (Добавлено as-is)
* Полная база IP-адресов из репозитория **Loyalsoldier/v2ray-rules-dat**. Все категории (ru, telegram и т.д.) импортируются без изменений.

---

## 👥 Источники данных (Upstream Credits)

| Репозиторий | Описание вклада в GeoGaga |
| :--- | :--- |
| [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite) | Базовые списки обхода, реклама, торренты |
| [hydraponique/roscomvpn-geoip](https://github.com/hydraponique/roscomvpn-geoip) | Российские подсети, исключения, приватные IP |
| [runetfreedom/russia-blocked-geosite](https://github.com/runetfreedom/russia-blocked-geosite) | Расширенная реклама, телеметрия Windows |
| [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) | Полная база доменов v2fly (As-Is) |
| [Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) | Полная база IP-адресов (As-Is) |

---

## 🔄 Автоматическое обновление

Сборка обновляется автоматически каждые сутки в **05:55 (GMT+3)** через **GitHub Actions**. Скрипт декомпилирует исходные `.dat` файлы, очищает дубликаты, проверяет пересечения IP-диапазонов, приводит имена категорий к верхнему регистру (`UPPERCASE`) для гарантированной совместимости с ядром и упаковывает результат в бинарный формат Protobuf.
