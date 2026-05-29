<p align="center">
  <img src="./banner.svg" alt="GeoGaga - Server Flavor Banner" width="100%">
</p>

## О проекте

**GeoGaga - Server Flavor** — это специализированная сборка гео-баз данных `geosite.dat` и `geoip.dat`, скомпилированная для использования непосредственно на стороне заграничного VPN-сервера под управлением Xray / Sing-box (в связке с панелями управления **3x-ui**, **Remnawave**, **Marzban** и др.).

В отличие от клиентской версии, данный релиз спроектирован для фильтрации и оптимизации трафика на самом сервере:
1. **Экономия ресурсов и трафика VPS** путем блокировки рекламы, трекеров, телеметрии ОС и тяжелого торрент-трафика "на подлете".
2. **Агрегирование специфичных правил обхода** в единые кастомные теги верхнего регистра.
3. **Сохранение совместимости** со стандартными мировыми правилами благодаря импорту полных баз DLC и Loyalsoldier в режиме `as-is`.

Сборка обновляется полностью автоматически каждые сутки в **05:55 (GMT+3)**.

---

## Структура файлов

Кастомные категории GeoGaga приведены строго к **ВЕРХНЕМУ РЕГИСТРУ** для гарантированной совместимости со всеми версиями Xray-core.

### geosite.dat
Агрегирует и пересобирает доменные зоны из различных проверенных апстримов:

| Целевая категория | Исходный репозиторий / Источник | Исходные категории | Описание назначения |
| :--- | :--- | :--- | :--- |
| **`GEOGAGA-PROXY`** | `hydraponique/roscomvpn-geosite` | `whitelist`, `category-ru` | Списки доменов, требующих проксирования/обработки на сервере |
| **`GEOGAGA-BLOCK`** | `hydraponique/roscomvpn-geosite` <br> `runetfreedom/russia-blocked-geosite` | `torrent`, `private`, `category-ads` <br> `category-ads-all`, `geosite:win-spy` | Реклама, трекеры, телеметрия Windows и торренты для сброса на сервере |
| *Оригинальные теги* | `v2fly/domain-list-community` | **Все категории AS-IS** (`google`, `netflix`, `apple` и т.д.) | Полная база DLC для классических правил маршрутизации |

### geoip.dat
Объединяет IP-диапазоны и пулы подсетей сетевого уровня (Routing Layer):

| Целевая категория | Исходный репозиторий / Источник | Исходные категории | Описание назначения |
| :--- | :--- | :--- | :--- |
| **`GEOGAGA-PROXY`** | `hydraponique/roscomvpn-geoip` | `direct`, `whitelist` | Диапазоны IP-адресов, подлежащие проксированию |
| **`GEOGAGA-BLOCK`** | `hydraponique/roscomvpn-geoip` | `private` | Локальные и приватные пулы адресов для блокировки на внешнем интерфейсе |
| *Оригинальные теги* | `Loyalsoldier/v2ray-rules-dat` | **Все категории AS-IS** (`cn`, `telegram`, `private` и т.д.) | Полная база Loyalsoldier для прямой работы с IP-правилами |

---

## Автоматизация сборки

GitHub Actions воркфлоу гарантирует стабильность и актуальность данных:
* **Protobuf-компиляция:** Скрипт налету выкачивает `.dat` релизы апстримов, декомпилирует их структуры, выполняет слияние и фильтрацию по заданным массивам данных и упаковывает обратно в бинарный формат.
* **Контроль целостности:** Для каждого релиза генерируются проверочные хэш-файлы (`geoip.dat.sha256` и `geosite.dat.sha256`).
* **Атомарный выпуск:** Новые файлы перезаписывают активы внутри постоянного релиза `latest`, предотвращая забивание истории тегов Git.

---

## Быстрый старт и интеграция

### 1. Скачивание баз на сервер
Пример bash-скрипта для обновления файлов в рабочей директории ядра Xray (пути могут отличаться в зависимости от архитектуры вашей панели, например `/var/lib/marzban/xray/` или `/usr/local/etc/xray/`):

```bash
cd /usr/local/share/xray/

# Скачивание актуальных баз данных
wget -O geosite.dat [https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geosite.dat](https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geosite.dat)
wget -O geoip.dat [https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geoip.dat](https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geoip.dat)

# Скачивание контрольных сумм
wget -O geosite.dat.sha256 [https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geosite.dat.sha256](https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geosite.dat.sha256)
wget -O geoip.dat.sha256 [https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geoip.dat.sha256](https://github.com/ВАШ_НИКНЕЙМ/GeoGaga-Server-Flavor/releases/latest/download/geoip.dat.sha256)

# Валидация файлов перед перезапуском службы
sha256sum -c geosite.dat.sha256
sha256sum -c geoip.dat.sha256
```

### 2. Настройка правил маршрутизации (Routing) в Xray

Пример конфигурационного блока правил для секции `routing.rules` в файле `config.json` вашего сервера:

```json
{
  "routing": {
    "domainStrategy": "AsIs",
    "rules": [
      {
        "type": "field",
        "domain": [
          "geosite:GEOGAGA-BLOCK"
        ],
        "outboundTag": "block_blackhole"
      },
      {
        "type": "field",
        "ip": [
          "geoip:GEOGAGA-BLOCK"
        ],
        "outboundTag": "block_blackhole"
      },
      {
        "type": "field",
        "domain": [
          "geosite:GEOGAGA-PROXY"
        ],
        "outboundTag": "proxy_upstream" 
      },
      {
        "type": "field",
        "ip": [
          "geoip:GEOGAGA-PROXY"
        ],
        "outboundTag": "proxy_upstream"
      }
    ]
  }
}
```
*Где `block_blackhole` — это ваш outbound с протоколом `blackhole` (для сброса пакетов), а `proxy_upstream` — имя основного исходящего интерфейса сервера (или следующего прокси-каскада).*
