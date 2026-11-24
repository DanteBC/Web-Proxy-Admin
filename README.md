# Web Proxy Admin

Веб-панель администратора для управления локальными пользователями 3proxy, ipset/ipтаблицами и policy-routing через интерфейс AmneziaWG. Приложение написано на FastAPI, использует SQLite по умолчанию и Jinja2-интерфейс.

Логика маршрутизации:

```text
трафик 3proxy OUTPUT
        |
        v
 цепочка WEBPROXY_AWG
        |
        +-- dst в awg-force -> MARK 1 -> таблица 100 -> awg1
        +-- dst в ru-direct  -> RETURN (обычная маршрутизация хоста)
        +-- всё остальное    -> MARK 1 -> таблица 100 -> awg1
```

## Состав

- `app/` — FastAPI, API, пользователи, правила, статистика и шаблон аутентификации;
- `scripts/route_awg.py` — создание ipset-наборов, iptables-цепочки и маршрута таблицы `100`;
- `app/templates/3proxy.cfg.j2` — пример конфигурации 3proxy;
- `deploy/webproxy.service` — пример systemd-unit;
- `deploy/route-helper.sudoers` — пример ограниченного sudo-доступа;
- `tests/` — тесты парсера логов и генерации пользователей.

## Требования

Linux-хост с:

- Python 3.11+;
- systemd;
- 3proxy;
- AmneziaWG или совместимый WireGuard-интерфейс, обычно `awg1` — фактическое имя задаётся настройкой `WEBPROXY_AWG_INTERFACE`;
- утилитами `ip`, `ipset`, `iptables`, `systemctl`;
- правами на применение netfilter-routing либо systemd capability;
- доступом к `/etc/3proxy/`, `/var/log/3proxy/` и базе приложения.

Проверка:

```bash
python3 --version
systemctl --version
command -v ip ipset iptables systemctl 3proxy
```

Debian/Ubuntu установка системных утилит:

```bash
sudo apt update
sudo apt install -y python3 python3-venv iproute2 ipset iptables
```

Пакет 3proxy лучше устанавливать из репозитория вашей ОС или из проверенного пакета для вашей системы. Сервис должен называться `3proxy.service`; если пакет использует другой unit, измените `WEBPROXY_PROXY_SERVICE`.

## Быстрый запуск для разработки

```bash
cd /path/to/web-proxy
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --host "${WEBPROXY_WEB_HOST:-127.0.0.1}" --port 8000 --reload
```

Установка через `.[dev]` необязательна для production: используйте `pip install -e .` или пакетный способ развёртывания.

По умолчанию приложение доступно локально по адресу `http://127.0.0.1:8000/login`. Чтобы запустить dev-сервер на другом IP, задайте `WEBPROXY_WEB_HOST` в shell перед запуском. Для IPv6-адреса используйте, например, `--host ::1`; в URL IPv6-адрес указывается в квадратных скобках.

Основные переменные окружения:

```dotenv
WEBPROXY_DATABASE_URL=sqlite:///./webproxy.db
WEBPROXY_SESSION_SECRET=случайная-длинная-строка
WEBPROXY_ADMIN_LOGIN=admin
WEBPROXY_ADMIN_PASSWORD=strong-password
WEBPROXY_WEB_HOST=127.0.0.1

WEBPROXY_PROXY_CONFIG=/etc/3proxy/3proxy.cfg
WEBPROXY_PROXY_USERS_FILE=/var/lib/web-proxy/users
WEBPROXY_PROXY_LOG_FILE=/var/log/3proxy/3proxy.log
WEBPROXY_PROXY_SERVICE=3proxy.service
WEBPROXY_PROXY_USER=3proxy
WEBPROXY_PROXY_USER=3proxy

WEBPROXY_ROUTING_SCRIPT=/usr/local/sbin/webproxy-routing
WEBPROXY_RU_URL=https://www.ipdeny.com/ipblocks/data/aggregated/ru-aggregated.zone
WEBPROXY_RU_FILE=
WEBPROXY_AWG_INTERFACE=awg1
WEBPROXY_ROUTING_TABLE=100
WEBPROXY_ROUTING_MARK=1
```

Сгенерируйте случайный ключ сессии:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Не используйте значение `change-me` за пределами тестового окружения.

## Настройка 3proxy

### 1. Создайте файлы

```bash
sudo install -d -m 0755 /etc/3proxy /var/log/3proxy
sudo install -d -m 0755 /run/3proxy
sudo touch /var/log/3proxy/3proxy.log
sudo chmod 0640 /var/log/3proxy/3proxy.log
sudo chown 3proxy:3proxy /var/log/3proxy/3proxy.log
```

Если в системе пользователь 3proxy называется иначе, замените имя во всех командах и в `WEBPROXY_PROXY_USER`.
Для совместного управления пользователями через панель используйте файл `/var/lib/web-proxy/users`: установщик создаёт каталог и добавляет системного пользователя 3proxy в группу `webproxy`, чтобы 3proxy мог читать файл, который атомарно обновляет приложение. После добавления группы перезапустите 3proxy один раз, чтобы процесс получил новое членство.

При ручной установке создайте группу/каталог и добавьте пользователя 3proxy в группу приложения:

```bash
getent group webproxy >/dev/null || sudo groupadd --system webproxy
sudo install -d -o webproxy -g webproxy -m 0750 /var/lib/web-proxy
sudo usermod -a -G webproxy 3proxy
```

### 2. Базовый `3proxy.cfg`

Пример из проекта можно адаптировать как `/etc/3proxy/3proxy.cfg`:

```text
daemon
pidfile /run/3proxy/3proxy.pid
log /var/log/3proxy/3proxy.log D
logformat "- %t\t%U\t%C\t%R\t%I\t%O\t%E\t%p\t%T"
rotate 30

nserver 1.1.1.1
nserver 8.8.8.8
nscache 65536
timeouts 1 5 30 60 180 1800 15 60

internal 0.0.0.0
external 0.0.0.0

auth strong
users $/var/lib/web-proxy/users

allow *
socks -p1080
proxy -p3128
```

Важно: у разных сборок 3proxy разные ключи/формат счетчиков и логов. Перед production-переходом проверьте бинарник:

```bash
sudo 3proxy --help
sudo 3proxy -v 2>&1 || true
sudo strings "$(command -v 3proxy)" | grep -E 'logformat|countin|countout|countall|counter' | sort -u
```

Не копируйте неизвестные директивы из различных сборок: сначала проверьте командой запуска и журналом конкретного сервиса.

### 3. Файл пользователей

Панель пишет строки в формате:

```text
alice:CL:пароль
bob:CL:пароль
```

Кавычки, двоеточия, переводы строк и пробелы в логине панель запрещает. Пароли в файле должны соответствовать требованиям конкретной сборки 3proxy. Если сборка использует хэшированный формат, в панели должно храниться и передаваться именно поддерживаемое сборкой значение.

Создать вручную пример:

```bash
sudo install -d -o webproxy -g webproxy -m 0750 /var/lib/web-proxy
sudo tee /var/lib/web-proxy/users >/dev/null <<'EOF'
alice:CL:strong-password
bob:CL:strong-password
EOF
sudo chmod 0640 /var/lib/web-proxy/users
sudo chown webproxy:webproxy /var/lib/web-proxy/users
```

### 4. Unit и перезагрузка

Проверьте существующий unit:

```bash
systemctl cat 3proxy
systemctl status 3proxy --no-pager
```

Для перезагрузки systemd должен поддерживать `ExecReload` или вызывать `SIGHUP`:

```ini
[Service]
ExecReload=/bin/kill -HUP $MAINPID
```

Если сборка не поддерживает reload без потери работы, добавьте отдельный unit-шаг с `ExecReload` и предварительно проверьте его на стенде.

После изменения конфигурации:

```bash
sudo 3proxy /etc/3proxy/3proxy.cfg
sudo systemctl restart 3proxy.service
sudo systemctl is-active 3proxy.service
sudo journalctl -u 3proxy.service -n 100 --no-pager
```

Вместо `restart` для штатного обновления используйте:

```bash
sudo systemctl reload 3proxy.service
```

Приложение также проверяет активное состояние через `systemctl is-active`.

## Настройка AmneziaWG

Основные требования:

1. ядро содержит AmneziaWG-модуль или пакеты AmneziaWG установлены;
2. интерфейс поднят под именем `awg1`;
3. туннель получает peer, ключи и адрес интерфейса из конфигурации;
4. маршрут default для таблицы `100` указывает именно на `awg1`;
5. при изменении состояния/переподключении туннеля route восстанавливается.

Проверьте интерфейс:

```bash
sudo ip link show awg1
sudo ip address show dev awg1
sudo wg show  awg1
sudo ip route show dev awg1
```

Установить default-route для отдельной таблицы вручную:

```bash
sudo ip route replace default dev awg1 table 100
sudo ip rule add priority 100 fwmark 1 lookup 100
sudo ip route flush cache
```

Проверка policy-routing:

```bash
sudo ip rule show
sudo ip route show table 100
sudo ip route get 1.1.1.1
sudo ip route get 1.1.1.1 mark 1
```

### Настройка при `Table = off` в профиле Amnezia

Параметр `Table = off` отключает автоматическое управление маршрутом в конфигурации Amnezia/WireGuard, а не отключает сам интерфейс и не означает отсутствие `AllowedIPs`. Приложение и routing-helper могут продолжать использовать отдельную таблицу, но для этого маршруты нужно создавать вручную или отдельным systemd-скриптом.

Сначала проверьте реальное состояние профиля и интерфейса:

```bash
sudo ip link show awg1
sudo ip address show dev awg1
sudo wg show awg1
sudo wg show awg1 allowed-ips
sudo ip route show dev awg1
sudo ip route show table 100
```

Создайте правила и route, если профиль не создал их автоматически:

```bash
sudo python3 scripts/route_awg.py --interface awg1 --table 100 --mark 1 --priority 100
```

Helper проверяет, не занят ли priority `100` конфликтующим правилом, создаёт правило через `ip rule add` только при необходимости и устанавливает default route:

```bash
sudo python3 /opt/web-proxy/scripts/route_awg.py \
  --interface awg1 --table 100 --mark 1 --priority 100 \
  --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
```

Если AWG уже был поднят утилитой Amnezia с `Table = off`, не запускайте общие `wg-quick`-команды для этого профиля. Проверьте точное имя интерфейса: старые/другие профили могут создать интерфейс не `awg1`, а `awg0`, `wg0` или другое имя. В панели укажите фактическое имя через аргумент `--interface` и замените имя в systemd unit.

Не удаляйте существующий маршрут peer-сервера или маршрут к серверу AWG из основной таблицы. При типичной конфигурации `AllowedIPs = 0.0.0.0/0` интерфейс сам не должен без необходимости перехватывать весь общий routing хоста, если для него отключено создание table-правил. Однако общий `AllowedIPs` всё равно означает, какие назначения tunnel-а могут принимать peer policy и route; фактический выбор таблицы обычно выполняется вашим правилом `fwmark`.

Проверьте fallback-маршрутизацию и отсутствие циклов:

```bash
sudo ip route get 1.1.1.1
sudo ip route get 8.8.8.8 mark 1
sudo ip route get 77.88.8.8 mark 1
```

`1.1.1.1` и `8.8.8.8` должны показывать `dev awg1 table 100` при маркировке `1`, если они принудительно не находятся в `ru-direct`. Российский адрес должен идти через обычный маршрут хоста и не иметь mark.

Для запуска при поднятии/переподключении AWG создайте systemd-службу или NetworkManager/dispatcher hook после поднятия интерфейса:

```ini
[Unit]
Description=Restore WebProxy policy routing
After=network-online.target awg.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/webproxy-routing --interface awg1 --table 100 --mark 1 --priority 100 --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone

[Install]
WantedBy=multi-user.target
```

После установки unit:

```bash
sudo install -m 0750 scripts/route_awg.py /usr/local/sbin/webproxy-routing
sudo tee /etc/systemd/system/webproxy-routing.service >/dev/null <<'EOF'
[Unit]
Description=Restore WebProxy policy routing
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/webproxy-routing --interface awg1 --table 100 --mark 1 --priority 100 --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now webproxy-routing.service
```

Unit должен стартовать после поднятия конкретного AWG-интерфейса. Добавьте зависимости вида `After=awg.service` или используйте dispatcher hook после успешного поднятия интерфейса; порядок запуска должен быть проверен командой `systemctl list-dependencies webproxy-routing.service`.

Если tunnel переподключается и AWG-инсталлятор не перезапускает интерфейс, route в таблице `100` можно сохранить, но при полном пересоздании `awg1` unit/router-helper должен запустить route повторно после появления интерфейса.

### `PostUp` / `PostDown` для профиля Amnezia

Если Linux-клиент AmneziaWG поддерживает обычные WireGuard-style hooks, упростить lifecycle можно прямо из секции `[Interface]` профиля:

```ini
[Interface]
Address = 10.0.0.2/32
PrivateKey = ...
DNS = ...
Table = off

PostUp = /usr/local/sbin/webproxy-routing --interface %i --table 100 --mark 1 --priority 100 --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
PostDown = ip route del default dev %i table 100 2>/dev/null || true; ip rule del priority 100 fwmark 1 lookup 100 2>/dev/null || true
```

`%i` означает фактическое имя поднятого интерфейса. Не фиксируйте `awg1` в hooks, если клиент может создать другой интерфейс; скрипт и адрес route должны получать имя через `%i`.

Несколько PostUp/PostDown команд разделяются точкой с запятой. Если версия клиента не выполняет `%i` или не поддерживает hooks, используйте systemd/NetworkManager hook вместо этих строк. Сами AWG-параметры профиля должны оставаться в формате вашего Amnezia-клиента, а не путаться с directive `Table`.

Обычно достаточно одного `PostUp`: routing helper сам создаёт ipset-наборы, цепочку iptables, policy rule и default route. Не добавляйте отдельный `ip rule replace`; `ip rule` не поддерживает эту команду на стандартном iproute2.

Если нужен локальный список, используйте `--ru-file /path/to/ru.zone` вместо `--ru-url ...`. Директивы PostUp/PostDown могут быть ограничены конкретной реализацией Amnezia; проверьте поддержку hooks и подстановки `%i`.

PostDown должен удалять только артефакты этого проекта:

```ini
PostDown = ip route del default dev %i table 100 2>/dev/null || true; ip rule del priority 100 fwmark 1 lookup 100 2>/dev/null || true
```

Не выполняйте общий `iptables -F`, не удаляйте чужие fwmark-правила и не разрушайте ipset через PostDown. Оставленные ipset-наборы и iptables-цепочка не будут отправлять traffic в таблицу `100` после удаления policy route, а отдельная очистка может небезопасно повлиять на конфигурацию хоста.

Перед установкой профиля проверьте права скрипта:

```bash
sudo install -m 0750 scripts/route_awg.py /usr/local/sbin/webproxy-routing
sudo chmod 0750 /usr/local/sbin/webproxy-routing
sudo visudo -c
```

Hook должен запускаться привилегированно пользователем системы. Не пытайтесь дать обычному пользовательскому процессу `sudo` с паролем внутри конфигурационного профиля. Лучший вариант для desktop-клиента — profile hook вызывает root-level helper через configured systemd/NetworkManager integration. На сервере скрипт устанавливают в `/usr/local/sbin` и запускают через network unit с правами root.

Если профиль хранит имя интерфейса и запускается обычным Amnezia-клиентом не через systemd, первый вариант — путь к helper и hook должны соответствовать установленной Amnezia/awg реализации. Проверьте фактический синтаксис и запустите hook вручную до сохранения профиля:

```bash
sudo /usr/local/sbin/webproxy-routing --interface awg1 --table 100 --mark 1 --priority 100 --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
sudo ip rule show
sudo ip route show table 100
sudo iptables -t mangle -n -v -L WEBPROXY_AWG
```

В результате work-flow упрощается:

- профиль создаёт интерфейс;
- `PostUp` восстанавливает/добавляет policy rule и route таблицы `100`;
- route-helper обновляет ipset и iptables без отдельного API-приложения;
- приложение может применять новые CIDR через тот же helper;
- `PostDown` удаляет только routing rule/route, не затрагивая другие системные правила;
- отдельный systemd unit нужен только как fallback для возврата маршрута после reboot или ошибки запуска профиля.

Команда `ip route get ... mark 1` доступна только если утилита/ядро поддерживают опцию `mark`. Запустите альтернативу через `ip rule` и таблицу при необходимости.

Команды AWG отличаются в зависимости от способа установки. Как правило, конфигурация загружается утилитами/скриптом провайдера или Amnezia клиента с последующим созданием интерфейса `awg1`. Не используйте общий `wg-quick` для конфигураций с AWG-параметрами, если установленная сборка не поддерживает их синтаксис.

Для автоматического восстановления интерфейса используйте NetworkManager/dispatcher или systemd unit вашего AWG-инсталлятора. Unit приложения должен запускаться после AWG:

```ini
[Unit]
After=network-online.target awg.service
Wants=network-online.target
```

## Установка и настройка ipset/iptables

Установите утилиты:

```bash
sudo apt install -y ipset iptables
sudo modprobe ip_set
sudo modprobe ip_set_hash_net
```

Наборы создаются автоматически скриптом `scripts/route_awg.py`:

```text
ru-direct  — прямые IPv4-сети России и ручные исключения;
awg-force  — адреса и сети, принудительно направляемые через AWG.
```

Можно проверить и создать вручную:

```bash
sudo ipset create ru-direct hash:net family inet hashsize 4096 maxelem 1048576
sudo ipset create awg-force hash:net family inet hashsize 4096 maxelem 1048576
```

Загрузка российского списка из URL:

```bash
sudo python3 scripts/route_awg.py \
  --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
```

Из локального файла:

```bash
sudo python3 scripts/route_awg.py --ru-file /opt/ipdeny/ru.zone
```

Добавить прямое исключение:

```bash
sudo ipset add ru-direct 192.0.2.10 -exist
sudo ipset add ru-direct 198.51.100.0/24 -exist
```

Через приложение или скрипт:

```bash
sudo python3 scripts/route_awg.py --direct 192.0.2.10 198.51.100.0/24
```

Принудительно через AWG:

```bash
sudo ipset add awg-force 8.8.8.8 -exist
sudo ipset add awg-force 1.1.1.0/24 -exist
sudo python3 scripts/route_awg.py --force-awg 8.8.8.8 1.1.1.0/24
```

Удаление элементов:

```bash
sudo ipset del ru-direct 198.51.100.0/24
sudo ipset del awg-force 8.8.8.8
sudo python3 scripts/route_awg.py \
  --remove-direct 198.51.100.0/24 \
  --remove-force-awg 8.8.8.8
```

Просмотр:

```bash
sudo ipset list ru-direct
sudo ipset list awg-force
sudo iptables -t mangle -n -v -L WEBPROXY_AWG
sudo iptables -t mangle -n -v -L OUTPUT
sudo ip rule show
sudo ip route show table 100
```

Скрипт создаёт цепочку `WEBPROXY_AWG` приблизительно в таком виде:

```text
-j MARK --set-mark 1    для awg-force
-j RETURN               для ru-direct
-j MARK --set-mark 1    для всего остального
```

Затем цепочка вызывается из `OUTPUT` для UID пользователя 3proxy:

```bash
sudo iptables -t mangle -C OUTPUT -m owner --uid-owner 3proxy -j WEBPROXY_AWG
sudo iptables -t mangle -A OUTPUT -m owner --uid-owner 3proxy -j WEBPROXY_AWG
```

Команды UID-owner требуют запуска 3proxy от отдельного пользователя и могут не охватывать traffic дочерних процессов. Скрипт определяет UID пользователя `--proxy-user` или `3proxy` автоматически.

Если 3proxy форвардит существующий traffic хоста вместо создания исходящего traffic как конкретного UID, маркируйте нужный входящий интерфейс/сетевой интерфейс отдельно и не используйте broad-JUMP на весь `OUTPUT`.

## Команды ручного iptables-шаблона

Сначала создайте наборы и цепочку:

```bash
sudo ipset create ru-direct hash:net family inet hashsize 4096 maxelem 1048576
sudo ipset create awg-force hash:net family inet hashsize 4096 maxelem 1048576

sudo iptables -t mangle -N WEBPROXY_AWG 2>/dev/null || true
sudo iptables -t mangle -F WEBPROXY_AWG

sudo iptables -t mangle -A WEBPROXY_AWG \
  -m set --match-set awg-force dst \
  -j MARK --set-mark 1 \
  -m comment --comment webproxy-awg-force

sudo iptables -t mangle -A WEBPROXY_AWG \
  -m set --match-set ru-direct dst \
  -j RETURN \
  -m comment --comment webproxy-direct

sudo iptables -t mangle -A WEBPROXY_AWG \
  -j MARK --set-mark 1 \
  -m comment --comment webproxy-awg-default

sudo iptables -t mangle -A OUTPUT \
  -m owner --uid-owner 3proxy \
  -j WEBPROXY_AWG \
  -m comment --comment webproxy-owned-output

sudo ip route replace default dev awg1 table 100
sudo ip rule add priority 100 fwmark 1 lookup 100
```

Не используйте `iptables -F` целиком. Скрипт панели не удаляет чужие цепочки и только очищает собственную цепочку `WEBPROXY_AWG`.

## Сохранение правил

`ipset`, `iptables`, `ip rule` и `ip route` обычно не сохраняются после reboot. Установите netfilter-persistent либо создайте systemd unit.

### iptables/netfilter-persistent

```bash
sudo apt install -y netfilter-persistent iptables-persistent
sudo netfilter-persistent save
```

Сохранить ipset:

```bash
sudo ipset save ru-direct > /tmp/ru-direct.ipset
sudo ipset save awg-force > /tmp/awg-force.ipset
sudo mkdir -p /etc/ipset
sudo ipset save > /etc/ipset/ipset.conf
```

После reboot:

```bash
sudo ipset restore -! -f /etc/ipset/ipset.conf
sudo iptables-restore -n < /etc/iptables/rules.v4
```

Уточните имена файлов и пакет netfilter-persistent для вашей версии ОС.

### Пример systemd для правил панели

```ini
[Unit]
Description=Restore 3proxy routing policy
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/webproxy-routing --interface awg1 --table 100 --mark 1 --priority 100 --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Для полной persistence установите скрипт в `/usr/local/sbin/webproxy-routing`:

```bash
sudo install -m 0750 scripts/route_awg.py /usr/local/sbin/webproxy-routing
sudo systemctl daemon-reload
sudo systemctl enable --now webproxy-routing.service
```

После reboot также должна восстановиться конфигурация AWG-интерфейса `awg1`. Скрипт проверяет наличие интерфейса и падает до изменения route, если интерфейс отсутствует.

## Установка скриптом

Установщик предназначен для Debian/Ubuntu с Python 3.11+ и запускается от root. Он устанавливает системные утилиты и Python, копирует приложение в `/opt/web-proxy`, создаёт пользователя `webproxy` и venv, сохраняет настройки в `/etc/web-proxy.env`, устанавливает routing helper и минимальные sudoers-правила для helper и reload 3proxy, затем включает `webproxy.service`.

Из корня проекта:

```bash
sudo ./scripts/install.sh
```

Для нового окружения установщик создаёт случайный пароль администратора и session secret. Пароль администратора выводится в конце установки один раз; сохраните его. Файл окружения имеет права `0600`.

Настройки сети можно задать при первой установке:

```bash
sudo env \
  WEBPROXY_WEB_HOST=192.0.2.10 \
  WEBPROXY_AWG_INTERFACE=awg1 \
  WEBPROXY_ROUTING_TABLE=100 \
  WEBPROXY_ROUTING_MARK=1 \
  WEBPROXY_ROUTING_PRIORITY=100 \
  WEBPROXY_RU_URL=https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone \
  ./scripts/install.sh
```

При повторном запуске существующий `/etc/web-proxy.env` сохраняется, а значения AWG-интерфейса, таблицы, mark, priority и URL для генерируемого sudoers берутся из него. Меняйте их в этом файле и затем повторно запускайте установщик, чтобы обновить sudoers. Установщик не удаляет базу данных и не изменяет существующую конфигурацию 3proxy или AmneziaWG.

`WEBPROXY_WEB_HOST` задаёт IP-адрес, на котором uvicorn принимает подключения. Допустим IPv4 или IPv6, назначенный этому серверу. Значение по умолчанию — `127.0.0.1`, то есть доступ только с самого хоста. Например, чтобы слушать на конкретном LAN-IP:

```dotenv
WEBPROXY_WEB_HOST=192.168.1.10
```

Для прослушивания на всех IPv4-интерфейсах можно указать `0.0.0.0`, но тогда обязательно ограничьте доступ firewall-ом или используйте reverse proxy с TLS и аутентификацией. Не публикуйте административную панель в открытый интернет. После изменения настройки перезапустите unit:

```bash
sudo systemctl restart webproxy.service
sudo systemctl status webproxy.service --no-pager
sudo ss -lntp | grep ':8000'
```

Для IPv6 укажите адрес, например `2001:db8::10`; URL в браузере будет иметь вид `http://[2001:db8::10]:8000/login`.

После установки проверьте состояние:

```bash
sudo systemctl status webproxy.service --no-pager
sudo journalctl -u webproxy.service -n 100 --no-pager
sudo visudo -c
curl -sSf http://127.0.0.1:8000/login >/dev/null
```

Установщик **не устанавливает 3proxy и AmneziaWG**, не поднимает туннель и не меняет профиль Amnezia. Настройте их отдельно. Для конфигурации с `Table = off` добавьте в секцию `[Interface]` профиля подходящие hooks, если Linux-клиент Amnezia их поддерживает:

```ini
Table = off
PostUp = /usr/local/sbin/webproxy-routing --interface %i --table 100 --mark 1 --priority 100 --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
PostDown = ip route del default dev %i table 100; ip rule del priority 100 fwmark 1 lookup 100 2>/dev/null || true
```

Если используются другие значения, подставьте их из `/etc/web-proxy.env`. Проверьте поддержку `PostUp`, `PostDown` и `%i` именно вашей версией Amnezia-клиента. Запустите helper вручную после поднятия интерфейса и проверьте `ip rule show`, `ip route show table 100` и цепочку `WEBPROXY_AWG` до включения hooks.

Скрипт не переписывает `/etc/3proxy/3proxy.cfg`. Убедитесь, что директива `users` указывает на значение `WEBPROXY_PROXY_USERS_FILE` (по умолчанию после установки — `/var/lib/web-proxy/users`). Не делайте весь `/etc/3proxy` доступным на запись пользователю панели.

## Ручная установка production-приложения

Создайте системного пользователя:

```bash
sudo useradd --system --home /opt/web-proxy --shell /usr/sbin/nologin webproxy
sudo install -d -m 0750 -o webproxy -g webproxy /var/lib/web-proxy
sudo install -d -m 0755 /opt/web-proxy
```

Скопируйте проект в `/opt/web-proxy`, создайте виртуальное окружение и установите зависимости:

```bash
cd /opt/web-proxy
sudo -u webproxy python3 -m venv .venv
sudo -u webproxy .venv/bin/pip install -e .
```

Установите sudoers-файл только после проверки абсолютного пути Python и скрипта:

```bash
sudo install -m 0440 deploy/route-helper.sudoers /etc/sudoers.d/webproxy-routing
sudo visudo -c
```

Пример sudoers позволяет запускать только конкретный скрипт с любыми аргументами. Для более строгой production-политики используйте разрешённый фиксированный набор аргументов и отдельный привилегированный daemon.

Установите systemd unit:

```bash
sudo install -m 0644 deploy/webproxy.service /etc/systemd/system/webproxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now webproxy.service
```

Рекомендуется использовать reverse proxy с TLS:

```text
Internet -> nginx/caddy -> 127.0.0.1:8000
```

Не публикуйте FastAPI прямо в интернет без reverse proxy и firewall.

## Статистика 3proxy

По умолчанию приложение читает `/var/log/3proxy/3proxy.log` построчно и агрегирует данные по имени пользователя и дате.

Шаблон проекта ожидает tab-separated формат:

```text
timestamp<TAB>username<TAB>client_ip<TAB>remote_host<TAB>bytes_in<TAB>bytes_out<TAB>...
```

Пример развёртывания шаблона логов в 3proxy:

```text
logformat "- %t\t%U\t%C\t%R\t%I\t%O\t%E\t%p\t%T"
```

Запись новых записей:

```bash
sudo tail -n 100 -F /var/log/3proxy/3proxy.log
```

Полный пересчёт через API:

```bash
curl -b 'session=<cookie>' \
  -X POST http://127.0.0.1:8000/api/statistics/collect
```

Через curl session-cookie создаётся только после входа в браузере или локального reverse proxy. Не передавайте сессию в публичные скрипты или shell-history.

Для production добавьте параллельный collector с:

- отслеживанием offset/inode при ротации;
- защитой от повторного чтения логов;
- ограничением пути и правами чтения;
- периодическим full reindex;
- поддержкой конкретного формата `counterin/countout/countall` или `3proxy-fup/JSON`, если используется эта сборка.

Проверьте активные соединения/счётчики вашей сборкой:

```bash
sudo ss -ntp | grep -E '1080|3128'
sudo journalctl -u 3proxy.service -n 100 --no-pager
sudo ls -la /var/lib/3proxy /var/log/3proxy
```

Не существует единого формата счётчиков для всех сборок 3proxy. Формат логов и counters нужно закрепить параметрами вашей конкретной сборки.

## Проверка и тесты

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q app scripts
```

Проверка Docker нет: приложение запускается непосредственно на Linux-хосте, где доступно управление ipset/iptables, AWG и systemd. Запуск в контейнере возможен только с корректными capability/host network и теми же systemd/service dependency.

Проверка установленного окружения:

```bash
curl -sSf http://127.0.0.1:8000/login >/dev/null
curl -sSf http://127.0.0.1:8000/openapi.json >/dev/null
systemctl is-active 3proxy.service
sudo ipset list ru-direct
sudo iptables -t mangle -n -L WEBPROXY_AWG
sudo ip rule show
sudo ip route show table 100  # замените 100, если задана другая WEBPROXY_ROUTING_TABLE
```

## Подводные камни

- Не используйте `iptables -F` целиком: скрипт должен очищать только собственную цепочку.
- Не удаляйте чужие `fwmark`, `ip rule`, routing table или ipset по общему имени.
- Для concurrent изменений используйте flock, который уже предусмотрен в routing helper.
- Атомарная замена ipset выполняется через temporary set + `swap`.
- При падении AWG удалите stale default route или восстановите route с новой интерфейсной конфигурацией.
- Изменение фактического имени AWG-интерфейса требует повторного создания default route в таблице `100` с актуальным значением `WEBPROXY_AWG_INTERFACE`.
- `rp_filter=1` может ломать asymmetric routing; проверяйте значения:

```bash
sudo sysctl net.ipv4.conf.all.rp_filter
sudo sysctl net.ipv4.conf.default.rp_filter
```

- Не запускайте панель от root и не доверяйте неограниченному shell доступу;
- ограничьте sudoers конкретным Python executable и конкретным скриптом;
- сохраняйте `iptables-save`, `ipset save`, `ip rule`, маршруты и 3proxy.cfg до применения;
- реализуйте rollback при ошибке reload или применения route;
- храните пароли БД, users-файла и session secret вне репозитория;
- всегда тестируйте на staging-хосте перед production, особенно изменение UID-owner, DNS, локальных подсетей и существующих правил policy routing.
