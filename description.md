В этой статье речь пойдет о разработке под отладочную плату LicheeRV Nano - компактное устройство размером с две пятирублевые монеты, но обладающее впечатляющими возможностями.

Плата способна одновременно запускать Linux и FreeRTOS, выполнять инференс нейронных сетей (будет разобран запуск YOLO и LLama2.c) благодаря встроенному NPU с производительностью 1 TOPS, а также управлять периферийными устройствами: GPIO, I2C, UART, SPI, CSI камерой, Wi-Fi, Bluetooth и Ethernet.

Это первая часть статьи, представляющая собой методическое руководство по работе с платой. Во второй части будет рассмотрена разработка полноценного проекта на её основе.

Обзор возможностей
SG2002
Плата построена вокруг SoC SG2002. Полный список аппаратных возможностей изображён на схемах ниже.

System Framework
System Framework
System Framework
System Framework
В первую очередь в глаза бросаются четыре отдельных ядра: два RISC-V с разными тактовыми частотами (1 GHz и 700 MHz), одно ядро ARM Cortex-A53 и одно ядро 8051. Разработчикам предоставляется выбор архитектуры “главного” ядра (на котором будет запускаться Linux) - ARM или RISC-V. Эти ядра не могут работать параллельно; выбор осуществляется посредством подтяжки определённого вывода микросхемы перед запуском. Однако разработчики LicheeRV Nano (Sipeed) заранее предопределили этот выбор: соответствующий пин изначально подтянут к линии 1,8 В, что приводит к запуску платы на RISC-V.


Для сравнения, на плате Milk-V Duo 256, использующей тот же SoC, линия CPU_SEL выведена на отдельный пин, что позволяет выбирать процессор вручную. Недавно был выпущен официальный образ операционной системы для ARM, но он пока не полностью функционален. В целом, акцент делается на архитектуру RISC-V, поэтому вся дальнейшая разработка под плату в статье будет под эту архитектуру.

Второе RISC-V ядро. Это ядро позиционируется как предназначенное для работы с RTOS. Для него уже портирована FreeRTOS. В результате получается архитектура, востребованная, например, в робототехнике: на быстром ядре с Linux выполняются задачи навигации, локализации и обработки видеопотока с камеры, а на ядре с FreeRTOS обсчитываются ПИД-регуляторы, одометрия и управление периферией - моторами, сервоприводами и другими актуаторами. Это даёт возможность создать компактное решение, заменяющее связку из отдельного микропроцессора и микроконтроллера (например, Raspberry Pi + STM32/Atmega).

Ядро 8051. Это ядро работает на низкой частоте и потребляет значительно меньше энергии по сравнению с основными ядрами. Оно имеет собственную систему питания и может управлять энергопотреблением других ядер, что позволяет реализовать режим энергосбережения (сон).

NPU и CSI. SoC оснащён нейронным процессором (NPU) с производительностью 1 TOPS при вычислениях с точностью INT8. В данной статье мы будем использовать его для инференса нейросети YOLO, которая выполняет детекцию объектов на кадрах, полученных с CSI камеры.

LicheeRV Nano
Вариации платы
Вариации платы
Существует 4 версии платы: с Ethernet портом, с WiFi трансивером, WiFi + Ethernet и базовая плата. Сама плата во всех версиях одинаковая, поэтому при желании на базовую плату вы можете сами припаять WiFi трансивер/Ethernet коннектор. У меня плата с WiFi (вместе с Bluetooth).

CPU

SG2002: 

1GHz RISC-V C906 / ARM A53

700MHz RISC-V C906

25 - 300 Mhz 8051

NPU

1TOPS INT8, поддержка BF16

Memory

256 Мб DDR3

IO

2 x 14 pins 2.54 mm

Размеры

22.86 x 35.56 mm

Документация и другая информация
Документация на плату находится здесь. Стоит обратить внимание на то, что в китайской версии в разделе “периферия” документация более подробная (больше информации про работу с различными интерфейсами). Я постепенно перевожу этот раздел на английский, но процесс принятия Pull Request’ов и обновления информации на сайте занимает некоторое время, поэтому можете обращаться к моему форку (хотя в этой статье про периферию написано больше). Либо просто используйте китайскую версию вместе с переводчиком. Также существует плата Milk-V Duo 256, которая также построена на базе SG2002, у них с документацией и форумом дела обстоят получше, часть информации можно найти там.

Основные фреймворки, которые будут упоминаться в статье:

CVI TDL SDK - набор готовых алгоритмов нейронных сетей, инференс которых проводится на NPU

TPU SDK - более низкоуровневый SDK для взаимодействия с NPU и периферией SoC’а

MMF (Multimedia Framework) - фреймворк с унифицированным API для работы с видео/изображениями/аудио на SoC’е

Все остальные ссылки/файлы, так же как и для прошлой статьи про Luckfox Pico я собрал в одном посте в телеграмм канале.

Энергопотребление
В даташите на SG2002 про энергопотребление сказано немного: “1080P + Video encode + AI : ~ 500mW”. Ниже я приведу графики энергопотребления платы в разных сценариях использования при питании от USB Type C.

Загрузка платы и скачивание файла через wget по http с другого компьютера в локальной сети:


Отправка файла через python http.server на компьютер из локальной сети, скачивающий файл с платы через wget:


Стрим CSI камеры в MJPEG через http на одного клиента:


Инференс YOLOv8n COCO на изображениях 640x640. Другие yolo модели имеют примерно такое же энергопотребление:


Инференс LLama (stories15M) на RISC-V CPU:


Отключение WiFi трансивера:


Работа с платой

Установка ОС
Официальный buildroot образ можно скачать из релизов в GitHub репозитории. Я использовал версию 20241021 (все примеры также были протестированы на более свежей версии - 20250114). Также под плату есть экспериментальный образ на базе Debian, но в нём отсутствуют драйвера под NPU и CSI камеру. 

В статье будет использоваться Buildroot образ, так как его легко конфигурировать и можно считать стандартом для Embedded Linux. 

Загрузка операционной системы происходит с SD карты. Записать на неё образ из под Linux’а можно с помощью dd:

xzcat "НАЗВАНИЕ.img.xz" | sudo dd of=/dev/sdX conv=sync status=progress
Объяснить с
Если архив с образом распакован, то команда примерно такая же:

cat "НАЗВАНИЕ.img" | sudo dd of=/dev/sdX conv=sync status=progress
Объяснить с
Вместо /dev/sdX подставляйте путь к вашей SD карте, она должна быть полностью отформатирована с таблицей разделов MBR (msdos), без разделов (без файловой системы, только неразмеченное пространство).

На Windows можете использовать Rufus или Balena Etcher.

У меня плата с WiFi модулем, поэтому сразу после прошивки образа можно сконфигурировать данные для подключения к WiFi сети, чтобы подключаться по ssh (он стартует автоматически). 

Для этого примонтируйте раздел rootfs (после прошивки SD карты на ней будет два раздела: boot и rootfs) и отредактируйте файл /etc/wpa_supplicant.conf следующим образом:

ctrl_interface=/var/run/wpa_supplicant
ap_scan=1
network={
  ssid="NAME"
  psk="PASSWORD"
}
Объяснить с
Замените NAME и PASSWORD на данные от своей сети. 

5G
Теперь можно извлекать SD карту, вставлять её в одноплатник и подавать на него питание. Если всё сделано правильно, то на одноплатнике сначала загорятся оба светодиода (красный - питание, синий - user), но затем синий светодиод начнёт мигать (если запускать плату без SD карты или с некорректным образом системы, то синий светодиод будет постоянно светиться).

Чтобы найти устройство в локальной сети, можно воспользоваться nmap (или любым другим сканером):

# поиск всех активных устройств в сети
sudo nmap -sN 192.168.1.0/24

# или сразу поиск по открытому 22 порту
nmap -sV -p 22 192.168.1.0/24
Объяснить с
Теперь можно подключаться через ssh (по умолчанию имя пользователя и пароль - root).

ssh root@192.168.1.21
Объяснить с
Если у вас плата без Ethernet или WiFi, то взаимодействовать с ней можно через отладочный UART0. Для этого подключите USB TTL переходник к пинам A17 (RX платы - TX переходника), A16 (TX платы - RX переходника) и общую землю.


Далее через терминальную программу (или screen на линуксе) вы можете взаимодействовать с платой на скорости 115200 бод.

screen /dev/ttyUSB0 115200
Объяснить с
Также имеется возможность работать с платой через ACM (/dev/ttyACM0) и локальную сеть поверх USB. Но для меня самыми удобными оказались ssh через WiFi и отладочный UART0 (в него плата посылает дополнительную отладочную информацию, которая иногда бывает полезна).

Плата имеет всего 256 Мб оперативной памяти (из которых 128 Мб занято под MIPI - CSI камеру и дисплей), чего может не хватать для некоторых задач. Решить эту проблему можно, добавив swap. Процесс можно перенести в Buildroot, чтобы итоговый образ уже был сконфигурирован с swap файлом, но самый простой способ - сделать его вручную, внутри работающей операционной системы. Все необходимые для этого утилиты идут из коробки в утилитах BusyBox:

fallocate -l 1G /swapfile # размер можете изменить на нужный вам
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
Объяснить с
Чтобы swap активировался автоматически после загрузки платы, необходимо добавить информацию о swap’е в fstab.

echo '/swapfile none swap sw 0 0' | tee -a /etc/fstab
Объяснить с
Теперь после перезагрузки swap будет автоматически активироваться.

Далее в статье будут примеры программ, использующих библиотеки OpenCV Mobile, TDL SDK, которые при сборке линкуются динамически, поэтому для запуска примеров, необходимо, чтобы на плате были их корректные версии. При использовании некорректных библиотек адекватной работы не добиться: TDL SDK работает очень медленно, перестаёт обрабатывать модели для cv181x, детектирует > 2000 классов на одном изображении, а также может быть конфликт между OpenCV Mobile и TDL SDK.

Все необходимые библиотеки я собрал здесь. Данный архив надо скачать и распаковать на плате:

# На компьютере
scp required_libs.zip root@192.168.X.X:/root

# На плате
cd /root
unzip required_libs.zip
export LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch/tpu_sdk_libs:/root/libs_patch:/root/libs_patch/opencv
Объяснить с
Установку правильного значения LD_LIBRARY_PATH можно автоматизировать (добавить export в конец файла /etc/profile):

echo "export LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch/tpu_sdk_libs:/root/libs_patch:/root/libs_patch/opencv" | tee -a /etc/profile
Объяснить с
Кастомная сборка Buildroot
Официальной сборки достаточно для первых простых тестов с платой, но для более сложных задач образ придется собирать из исходников. Кроме того, официальный образ содержит очень много лишнего (он весит 1.2 Gb, что немало). Например, в нём есть Python и куча ненужных библиотек для него. Использование Python на этой плате нецелесообразно, ввиду ограниченности ресурсов. Также образ универсальный для всех плат, т.е. если вы не используете WiFi или Ethernet, то вам и в образе не нужны драйверы для них. По-хорошему buildroot надо конфигурировать и собирать “с нуля” под конкретный набор задач, но на это потребуется много времени, поэтому в этой статье рассмотрим модификацию официального образа.

Его исходники находятся в GitHub репозитории. Сборку проще всего проводить в Docker контейнере, чтобы не было проблем с зависимостями, нужными для основной системы и компиляторам/сборщикам образа.

Для этого сначала скачаем исходники и соберём Docker контейнер:

git clone https://github.com/sipeed/LicheeRV-Nano-Build --depth=1
cd LicheeRV-Nano-Build
git clone https://github.com/sophgo/host-tools --depth=1
cd host/ubuntu
docker build -t licheervnano-build-ubuntu .
Объяснить с
Для запуска контейнера используем следующую команду:

docker run -v /path/to/LicheeRV-Nano-Build/:/workspace -it licheervnano-build-ubuntu /bin/bash
Объяснить с
Вместо “/path/to/LicheeRV-Nano-Build/” нужно указать путь к скачанному ранее git репозиторию LicheeRV-Nano-Build. В итоге после запуска, в контейнере будет директория /workspace, в которой и происходит сборка Buildroot’а. Она синхронизируется с директорией LicheeRV-Nano-Build на вашей основной системе, поэтому после остановки контейнера все изменения и кэшированные бинарники сохранятся.

Для полной сборки образа нужно выполнить следующие действия:

cd /workspace # переход в директорию с исходниками
source build/cvisetup.sh # настройка окружения
defconfig sg2002_licheervnano_sd # выбор конфига под RISC-V ядро
git config --global --add safe.directory /workspace

build_all
Объяснить с
Первая сборка займёт достаточно много времени, но последующие будут гораздо быстрее, потому что компилироваться будут только изменившиеся части. После сборки готовый к прошивке образ будет находиться в директории: /workspace/install/soc_sg2002_licheervnano_sd/images

Также можно собирать только отдельные компоненты системы, список команд ниже:

build_fsbl      # сборка fsbl (First Stage Bootloader), на выходе fip.bin
build_uboot  # сборка загрузчика uboot
build_rtos     # сборка freertos
build_kernel # сборка ядра linux
Объяснить с
Конфигурация отдельных частей Buildroot’а будет подробнее описана в следующих разделах, здесь же я приведу краткое описание того, что где находится и конфигурируется.

В корне репозитория (директория /workspace в контейнере) можно вызвать menuconfig с общими настройками:

menuconfig
Объяснить с
Общий menuconfig от CVITEK
Общий menuconfig от CVITEK
Здесь можно настроить версию ядра Linux, драйвера под CSI камеры и некоторые пакеты.

Сохранять изменения нужно в файл (чтобы после перезапуска контейнера для сборки изменения сохранились):

/workspace/build/boards/sg200x/sg2002_licheervnano_sd/sg2002_licheervnano_sd_defconfig

В директории /workspace/buildroot можно выполнить make menuconfig для его настройки.

menuconfig Buildroot
menuconfig Buildroot
После изменении конфигурации её нужно сохранять в файл:

/workspace/buildroot/configs/cvitek_SG200X_musl_riscv64_defconfig

В директории /workspace/linux_5.10 находятся исходники ядра, которое так же можно сконфигурировать через menuconfig.

menuconfig Linux kernel
menuconfig Linux kernel
После изменении конфигурации её нужно сохранить в файл:

/workspace/build/boards/sg200x/sg2002_licheervnano_sd/linux/sg2002_licheervnano_sd_defconfig

Конфигурировать мультиплексор (PINMUX) можно перед запуском Linux’а через U-Boot в файле /workspace/build/boards/sg200x/sg2002_licheervnano_sd/u-boot/cvi_board_init.c. Более подробно процесс конфигурации будет описан в разделе GPIO.

Device Tree описывается в файле:

/workspace/build/boards/sg200x/sg2002_licheervnano_sd/dts_riscv/sg2002_licheervnano_sd.dts

Hello, world!
Все примеры в виде готовых структурированных проектов с Makefile/CMake (для некоторых) можно взять из моего GitHub репозитория.

git clone https://github.com/ret7020/LicheeRVNano
Объяснить с
Текущий пример находится в Projects/HelloWorld.

Разработка под плату будет вестись на языках C/C++. Кросс-компилятор можно скачать здесь. В архиве находится три варианты кросс-компилятора. Официальный Buildroot образ использует musl реализацию libc, поэтому необходимо использовать riscv64-linux-musl-x86_64.

В директории riscv64-linux-musl-x86_64/bin находится бинарник gcc с названием riscv64-unknown-linux-musl-gcc.

Кросс-компилятор работает только под x86 Linux, но я подготовил специальный Jupyter ноутбук на Google Colab, благодаря которому проекты под плату можно собирать прямо в браузере практически на любой системе (главное, чтобы работал браузер). По опыту статьи про Luckfox такой метод оказался для некоторых актуальным и удобным.

Google Colab Jupyter Notebook для кросс-компиляции
Google Colab Jupyter Notebook для кросс-компиляции
В некоторых примерах, где используется ioctl (например, работа с sysfs - gpio) могут возникнуть проблемы при компиляции, которые решаются правкой ioctl.h (./gcc/riscv64-linux-musl-x86_64/sysroot/usr/include/sys/ioctl.h): необходимо закомментировать 9 строку (#include <bits/alltypes.h>). В Google Colab ноутбуке кросс-компилятор патчится автоматически.

Все следующие примеры используют переменную окружения COMPILER, чтобы получить абсолютный путь к кросс-компилятору. В ней необходимо указать путь к бинарникам кросс-компилятора.

export COMPILER=/ПУТЬ/К/КОМПИЛЯТОРУ/gcc/riscv64-linux-musl-x86_64/bin
Объяснить с
Замените /ПУТЬ/К/КОМПИЛЯТОРУ на свой.

Исходный код примера:

#include <stdio.h>

int main(){

	printf("Hello, world from LicheeRV Nano!\n");
	return 0;
}
Объяснить с
Makefile:

build:
	mkdir -p bin
	echo Using: ${COMPILER}
	${COMPILER}/riscv64-unknown-linux-musl-gcc main.c -o ./bin/hello 

deploy:
	scp ./bin/hello root@${LICHEERV_IP}:/root/hello
Объяснить с
Если в переменную окружения LICHEERV_IP записать IP адрес платы, то можно использовать make deploy, чтобы после компиляции загружать бинарник на плату через scp. Также большинство Linux’овых файловых менеджеров поддерживают протокол sftp, через который удобно работать с файлами на плате.

При отладке ПО на плате полезно смотреть логи. Основные источники логов:

dmesg
cat /var/log/messages # при отладке проектов с TDL SDK (чтение камеры, инференс нейронок) очень полезно
cat /proc/cvitek/vi_dbg # отладочная информация по VI (video input), т.е. CSI камеры
cat /proc/cvitek/vi # информация о CSI камере
cat /proc/mipi-rx
Объяснить с
И конечно же ещё могут оказаться полезными, логи идущие на отладочный UART0.

Логи на стороне Linux ядра
Логи на стороне Linux ядра
Периферия с Linux
В этом разделе будет рассказано, как использовать различные аппаратные возможности платы.

GPIO
На скриншоте опечатка: пин GPIO A15 в Linux имеет номер 495
На скриншоте опечатка: пин GPIO A15 в Linux имеет номер 495
На скриншоте выше показана распиновка платы. Чтобы работать с пинами из под Linux’а нам нужно знать их номера (второе трехзначное число, напротив каждого пина на схеме сверху). Все пины идут через мультиплексор, поэтому нам необходимо выбирать какой пин от SoC’а идёт на определённый пин на плате. Таким образом мы можем выбрать, например, задачу пина GPIO P18 - UART/I2C/PWM/SPI.

Адреса пинов в мультиплексоре описаны в старой версии (1.0) даташита на SG2002 в главе “10.1 PINMUX”. Но лучше использовать эту таблицу (лист “1. QFN”), она намного удобнее.

Также стоит обратить внимание на то, что некоторые пины могут быть заняты другой периферией на плате. WiFi модуль занимает пины с P18 по P23 и пин A26. Bluetooth использует пины A18, A19, A28, A29.

Сконфигурировать работу пина можно в процессе запуска платы через U-Boot или уже внутри запущенной операционной системы с помощью утилиты devmem. При этом конфигурация пина через U-Boot потребует пересборки и обновления загрузчика. Рассмотрим оба варианта.

Конфигурация в U-Boot. Для этого необходимо отредактировать функцию cvi_board_init файле /workspace/build/boards/sg200x/sg2002_licheervnano_sd/u-boot/cvi_board_init.c

Например, если у вас плата без WiFi модуля или он вам не нужен, то вы можете закомментировать следующие строки:

// (строки 66-89)
// wifi power reset
mmio_write_32(0x0300104C, 0x3); // GPIOA 26
val = mmio_read_32(0x03020004); // GPIOA DIR
val |= (1 << 26); // output
mmio_write_32(0x03020004, val);

val = mmio_read_32(0x03020000); // signal level
val &= ~(1 << 26); // set level to low
mmio_write_32(0x03020000, val);

suck_loop(50);
user_led_toggle();
val = mmio_read_32(0x03020000); // signal level
val |= (1 << 26); // set level to high
mmio_write_32(0x03020000, val);

// wifi sdio pinmux
mmio_write_32(0x030010D0, 0x0); // D3
mmio_write_32(0x030010D4, 0x0); // D2
mmio_write_32(0x030010D8, 0x0); // D1
mmio_write_32(0x030010DC, 0x0); // D0
mmio_write_32(0x030010E0, 0x0); // CMD
mmio_write_32(0x030010E4, 0x0); // CLK
Объяснить с
Чтобы перевести пин в GPIO режим (или любой другой) нам нужно узнать его адрес по таблице мультиплексора. Продемонстрирую на примере пина A24. Для этого в таблице ищем “XGPIOA[24]”.

Примера описания пина в таблице
Примера описания пина в таблице
Адрес пина - третий слева столбец, в данном случае его значение - 0x03001060, а значение для выбора режима 0x03 (по последнему столбцу).

При конфигурации через U-Boot добавьте вызов функции mmio_write_32(АДРЕС, ЗНАЧЕНИЕ) внутри cvi_board_init:

// GPIO A24 PINMUX
mmio_write_32(0x03001060, 0x03)
Объяснить с
Далее необходимо пересобрать U-Boot и обновить образ на плате.

Если времени на пересборку и обновление операционной системы нет, то для тестов, мультиплексор можно переконфигурировать внутри запущенного Linux’а. После перезагрузки все изменения сбросятся до тех, которые описаны в U-Boot, но для экспериментов этого достаточно. Для такой конфигурации можно воспользоваться утилитой devmem, в официальном образе её из коробки нет, но можно скачать бинарник под плату здесь.

Пример использования для пина A24:

./devmem 0x03001060 b 0x03
Объяснить с
Если всё сделано правильно, то вывод будет примерно таким:

/dev/mem opened.
Memory mapped at address 0x3fcaa97000.
Value at address 0x3001060 (0x3fcaa97060): 0x3
Written 0x3; readback 0x3
Объяснить с
Теперь пин сконфигурирован как цифровой GPIO. Управлять им можно с помощью Linux API, gpio sysfs. То есть записыванием нужных значений в различные файлы в директории /sys/class/gpio. В Linux пин A24 имеет номер 504 (из схемы выше).

Пример взаимодействия через терминал:

# Экспортируем в userspace
echo 504 > /sys/class/gpio/export

# Переводим его в режим “выхода”
echo out > /sys/class/gpio/gpio504/direction

# Устанавливаем его в HIGH
echo 1 > /sys/class/gpio/gpio504/value

# Устанавливаем его в LOW
echo 0 > /sys/class/gpio/gpio504/value

# В конце делаем unexport
echo 504 > /sys/class/gpio/unexport
Объяснить с
Для проверки можно воспользоваться простым bash скриптом, который генерирует меандр:

while true; do
	 echo 0 > /sys/class/gpio/gpio504/value
	 sleep 0.1
	 echo 1 > /sys/class/gpio/gpio504/value
	 sleep 0.1
done
Объяснить с
Меандр
Меандр
Аналогично можно программно управлять пином из C кода. 

Пример кода в Projects/GPIO.

Для удобства я написал отдельные функции и выделил их в файл gpio.h (ниже основные функции):

int exportPin(int pin)
{
	FILE *exportFile = fopen("/sys/class/gpio/export", "w");
	if (exportFile == NULL)
    	return -1;
	fprintf(exportFile, "%d", pin);
	fclose(exportFile);

	return 0;
}

int unexportPin(int pin)
{
	FILE *exportFile = fopen("/sys/class/gpio/unexport", "w");
	if (exportFile == NULL)
    	return -1;
	fprintf(exportFile, "%d", pin);
	fclose(exportFile);

	return 0;
}

int setDirPin(int pin, const char *dir)
{
	char directionPath[50];
	snprintf(directionPath, sizeof(directionPath), "/sys/class/gpio/gpio%d/direction", pin);
	FILE *directionFile = fopen(directionPath, "w");
	if (directionFile == NULL)
    	return -1;
	fprintf(directionFile, dir);
	fclose(directionFile);

	return 0;
}

int writePin(int pin, int value)
{
	char valuePath[50];
	snprintf(valuePath, sizeof(valuePath), "/sys/class/gpio/gpio%d/value", pin);
	FILE *valueFile = fopen(valuePath, "w");
	if (valueFile == NULL)
    	return -1;

	if (value)
    	fprintf(valueFile, "1");
	else
    	fprintf(valueFile, "0");
	fflush(valueFile);
	fclose(valueFile);

	return 0;
}

int setPin(int pin, int value) // wrapper
{
	return exportPin(pin) + setDirPin(pin, "out") + writePin(pin, value) + releasePin(pin);
}
Объяснить с
Пример их использования (digitalTest.c):

#include <stdio.h>
#include "gpio.h"

int main(){
	int pinId = 0;
	int pass = 0;
	scanf("%d", &pinId);
	printf("Working with pin: %d\n", pinId);
	exportPin(pinId);
	setDirPin(pinId, "out");
	writePin(pinId, 1);
	printf("Write 1\n");
	scanf("%d", &pass);

	writePin(pinId, 0);
	printf("Write 0\n");
	unexportPin(pinId);

	return 0;
}
Объяснить с
make build_digital
Объяснить с
Программа считывает номер пина из stdin (нужно вводить номер в Linux’е), записывает в него 1 и ждет ввода любого символа, после чего выключает пин (записывает 0) и освобождает его (корректно завершает работу с ним в sysfs).

PWM
Пример кода в Projects/GPIO. 

Конфигурация мультиплексора под PWM пины аналогична GPIO пинам.

PWM функции пинов в таблице
PWM функции пинов в таблице
Из под линукса взаимодействие с ними происходит также через sysfs. 

Конфигурация мультиплексора:

./devmem 0x03001068 b 0x2 # PWM 6
./devmem 0x03001064 b 0x2 # PWM 7
Объяснить с
Внутри SG2002 находится 4 шим контроллера, каждый на 4 канала. Следовательно PWM пины распределены между ними таким образом:

pwmchip0

PWM[0, 1, 2, 3]

pwmchip4

PWM[4, 5, 6, 7]

pwmchip8

PWM[8, 9, 10, 11]

pwmchip12

PWM[12, 13, 14, 15]

В таблице в правом столбце приведены абсолютные номера шим каналов, но при экспорте пина нужно указывать номер канала внутри контроллера. То есть PWM 7 находится внутри pwmchip4 с номером 7 - 4 = 3. У PWM 6 номер 2.

Управление через bash, на примере PWM 6 и PWM 7:

# PWM 6
echo 2 > /sys/class/pwm/pwmchip4/export
echo 10000 > /sys/class/pwm/pwmchip4/pwm2/period
echo 5000 > /sys/class/pwm/pwmchip4/pwm2/duty_cycle
echo 1 > /sys/class/pwm/pwmchip4/pwm2/enable

# PWM 7
echo 3 > /sys/class/pwm/pwmchip4/export
echo 10000 > /sys/class/pwm/pwmchip4/pwm3/period
echo 2500 > /sys/class/pwm/pwmchip4/pwm3/duty_cycle
echo 1 > /sys/class/pwm/pwmchip4/pwm3/enable
Объяснить с
Работа двух ШИМ каналов
Работа двух ШИМ каналов
Для управления PWM пинами из кода я написал две функции в gpio.h:

int pwmSetParam(int pin, int val, int type){
    // type == 0: set pwm period
    // type == 1: set pwm duty cycle
    // type == 2: set enable/disable (1/0)
    char typeMap[3][15] = {"period", "duty_cycle", "enable"};
    char valPath[50];
    snprintf(valPath, sizeof(valPath), "/sys/class/pwm/pwmchip4/pwm%d/%s", pin, typeMap[type]);
    printf("Path: %s\n", valPath);

    FILE *exportFile = fopen(valPath, "w");
    if (exportFile == NULL)
        return -1;
    fprintf(exportFile, "%d", val);
    fclose(exportFile);

    return 0;
}

int pwmUnexport(int pin){
    FILE *exportFile = fopen("/sys/class/pwm/pwmchip4/unexport", "w");
    if (exportFile == NULL)
        return -1;
    fprintf(exportFile, "%d", pin);
    fclose(exportFile);

    return 0;

}
Объяснить с
Эти функции захардкожены под pwmchip4, потому что пины остальных контроллеров заняты другими функциями, поэтому управлять ими нет необходимости.

Пример использования:

#include <stdio.h>
#include "gpio.h"

int main(){
    int pin = 0, period = 0, dutyCycle = 0, enableStatus = 0; 
    while (1) {
        printf("Pin (PWM_X, supported: 3 (pwm7) and 2 (pwm6)): \n");
        scanf("%d", &pin);
        printf("Period; duty cycle; enable/disable: \n");
        scanf("%d %d %d", &period, &dutyCycle, &enableStatus);
        printf("Export status: %d\n", pwmExport(pin));
        printf("Setting period: %d\n", pwmSetParam(pin, period, 0));
        printf("Setting duty cycle: %d\n", pwmSetParam(pin, dutyCycle, 1));
        printf("Setting enable: %d\n", pwmSetParam(pin, enableStatus, 2));
        pwmUnexport(pin);
    }
    

    return 0;
}
Объяснить с
make build_pwm
Объяснить с
После запуска программы необходимо ввести номер канала четвёртого PWM контроллера (2 или 3, соответствующие пинам PWM6 и PWM7 на плате) и настройки модуляции.

Прерывания
Пример кода в Projects/Interrupts.

В данном примере будет показана обработка прерываний средствами Linux’а (poll/select), то есть без настройки полноценных прерываний в dts. Скорость реакции на такие прерывания ниже, чем у полноценных, так как на самом деле идёт опрос состояния пина, но для большинства задач этого хватает. 

Пример кода, отслеживающий “rising” прерывания на пине A15 (в официальном образе сконфигурирован, как GPIO, поэтому перенастройка мультиплексора не требуется):

#include <stdio.h>
#include <poll.h>
#include <pthread.h>
#include "gpio.h"

int main()
{
	exportPin(GPIOA_15);
	setDirPin(GPIOA_15, "in");
	setInterruptType(GPIOA_15, "rising");

	char valuePath[50];
	snprintf(valuePath, sizeof(valuePath), "/sys/class/gpio/gpio%d/value", GPIOA_15);
	int fd = open(valuePath, O_RDONLY | O_NONBLOCK);
	if (fd < 0)
	{
		perror("Unable to open GPIO value file");
		return 1;
	}
	struct pollfd pfd;
	pfd.fd = fd;
	pfd.events = POLLPRI;

	// Read first 'init' interrupt
	poll(&pfd, 1, -1);
	lseek(fd, 0, SEEK_SET);
	char tmp[3];
	read(fd, tmp, sizeof(tmp));

	while (1)
	{
		int ret = poll(&pfd, 1, -1);
		if (ret > 0)
		{
			char buf[3];
			lseek(fd, 0, SEEK_SET);
			read(fd, buf, sizeof(buf));
			printf("Interrupt detected!\n");
		}
	}

	close(fd);

	return 0;
}
Объяснить с
Настройка пина реализована в gpio.h:

int setInterruptType(int pin, const char *type)
{
    char interruptPath[50];
    snprintf(interruptPath, sizeof(interruptPath), "/sys/class/gpio/gpio%d/edge", pin);
    FILE *interruptFile = fopen(interruptPath, "w");
    if (interruptFile == NULL)
        return -1;
    fprintf(interruptFile, type);
    fclose(interruptFile);

    return 0;
}
Объяснить с
UART
Пример кода в Projects/Interfaces/UART.

На плате выведено 4 UART’а: UART0 - отладочный, UART1 и UART2 (если не используется bluetooth) можно использовать для своих задач, а UART3 доступен только, если выключен WiFi.

Рассмотрим пины A28 и A29. Мультиплексор для этих пинов имеет интересную особенность, на них может работать оба (1 и 2) UART’а:

UART в таблице пинов
UART в таблице пинов
На распиновке пины A28 и A29 отмечены как UART2:

UART1 и UART2
UART1 и UART2
При этом никто не запрещает сконфигурировать их так, чтобы на них шёл сигнал с аппаратного UART1. Этот факт нужно учитывать при конфигурации мультиплексора.

Если есть необходимость использовать сразу оба UART’а, то ещё нужны адреса для пинов A19 и A18:


Их, кстати, может использовать только UART1 (и остальная периферия).

Пример использования UART1 на пинах A18 (RX), A19 (TX):

# Конфигурация мультиплексора
./devmem 0x03001068 b 0x6 # GPIOA 18 UART1 RX
./devmem 0x03001064 b 0x6 # GPIOA 19 UART1 TX
Объяснить с
Код:

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>

#define UART_PATH "/dev/ttyS1"

int main()
{
	printf("UART test %s\n", UART_PATH);
	char serialPort[] = UART_PATH;
	char txBuf[] = "abcd";
	struct termios tty;
	ssize_t writeLen;
	int serialFd;
	char rxBuffer[256];
	int bytesRead;

	serialFd = open(serialPort, O_RDWR | O_NOCTTY);
	printf("%d\n", serialFd);

	memset(&tty, 0, sizeof(tty));

	// Setting baud
	cfsetospeed(&tty, B115200);
	cfsetispeed(&tty, B115200);

	// Generic flags
	tty.c_cflag &= ~PARENB;
	tty.c_cflag &= ~CSTOPB;
	tty.c_cflag &= ~CSIZE;
	tty.c_cflag |= CS8;

	while (1)
	{
		writeLen = write(serialFd, txBuf, sizeof(txBuf));
		printf("%d\n", writeLen);
		usleep(50000);
	}

	return 0;
}
Объяснить с
UART1 TX
UART1 TX
SPI
SPI SCK и SPI MOSI
SPI SCK и SPI MOSI
Пример кода в Projects/Interfaces/SPI.

SG2002 имеет 3 аппаратных SPI. На плате выведен только один - SPI2, который при использовании WiFi занят под него. SPI4 - эмулируется через BitBang драйвер.

В этой статье будет рассмотрено использование аппаратного SPI2, при отключенном WiFi модуле.

Конфигурация мультиплексора:

/etc/init.d/S30wifi stop # корректная остановка wifi (чтобы потом без перезагрузки включить обратно)
./devmem 0x030010D0 b 0x1 # GPIO P18 CS
./devmem 0x030010DC b 0x1 # GPIO P21 MISO
./devmem 0x030010E0 b 0x1 # GPIO P22 MOSI
./devmem 0x030010E4 b 0x1 # GPIO P23 SCK
Объяснить с
Если у вас плата с WiFi, то вы можете без перезагрузки восстановить работоспособность WiFi модуля:

./devmem 0x030010D0 b 0x0
./devmem 0x030010DC b 0x0
./devmem 0x030010E0 b 0x0
./devmem 0x030010E4 b 0x0
/etc/init.d/S30wifi start
Объяснить с
Для быстрой проверки можно воспользоваться предустановленной утилитой spidev_test, также соединив MISO (P21) и MOSI (P22), образовав некоторый физический “loopback”:

spidev_test -D /dev/spidev2.0 -p "hello, world!" -v
Объяснить с
Результат должен быть примерно таким:

Максимальная скорость при которой сообщения совпадали (TX и RX) - 93 MHz
Максимальная скорость при которой сообщения совпадали (TX и RX) - 93 MHz
Пример кода для программного взаимодействия с SPI:

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <linux/spi/spidev.h>
#include <sys/ioctl.h>

#define SPI_DEVICE_PATH "/dev/spidev2.0"

int main()
{
	int spi_file;
	uint8_t tx_buffer[5] = {1, 2, 3, 4, 5};
	uint8_t rx_buffer[5];

	// Open the SPI device
	if ((spi_file = open(SPI_DEVICE_PATH, O_RDWR)) < 0)
	{
		perror("Failed to open SPI device");
		return -1;
	}

	uint8_t mode = SPI_MODE_0;
	uint8_t bits = 8;
	if (ioctl(spi_file, SPI_IOC_WR_MODE, &mode) < 0)
	{
		perror("Failed to set SPI mode");
		close(spi_file);
		return -1;
	}

	struct spi_ioc_transfer transfer = {
		.tx_buf = (unsigned long)tx_buffer,
		.rx_buf = (unsigned long)rx_buffer,
		.len = sizeof(tx_buffer),
		.speed_hz = 1000000,  // SPI speed in Hz
		.delay_usecs = 0,
		.bits_per_word = 8,
	};
	
	if (ioctl(spi_file, SPI_IOC_MESSAGE(1), &transfer) < 0)
	{
		perror("Failed to perform SPI transfer");
		close(spi_file);
		return -1;
	}
	for (uint8_t i = 0; i < 5; i++) {printf("%d ", rx_buffer[i]);}
	printf("\n");


	close(spi_file);

	return 0;
}
Объяснить с
Программа отправляет 5 байт (1, 2, 3, 4, 5) и выводит ответ, в случае с соединёнными MOSI и MISO ответ тоже будет “1 2 3 4 5”.

I2C
AHT20 + BMP280 + LicheeRV Nano
AHT20 + BMP280 + LicheeRV Nano
Пример кода в Projects/Interfaces/I2C.

SG2002 имеет 5 аппаратных I2C. На плате выведены только 2: 1, 3. Их пины также пересекаются с пинами для WiFi, поэтому эксперименты с I2C будут проводиться с выключенном WiFi модулем. I2C-5 программно эмулируется через BitBang драйвер.

В качестве примера будет продемонстрирована работа с модулем AHT20 (датчик влажности и температуры) + BMP280 (барометр). Он будет подключен на I2C-1, соответствующая конфигурация мультиплексора:

/etc/init.d/S30wifi stop # корректная остановка WiFi

./devmem 0x030010D0 b 0x2 # GPIO P18 SCL
./devmem 0x030010DC b 0x2 # GPIO P21 SDA
Объяснить с
Теперь с помощью i2cdetect можно узнать адреса модулей:

i2cdetect -ry 1
Объяснить с
Вывод будет примерно таким:

0x38 и 0x77
0x38 и 0x77
0x38 - адрес AHT20
0x77 - адрес BMP280

Для ручного тестирования можно использовать команды: 

i2cget - прочитать значение регистра

i2cset - записать значение в регистр

i2cdump - прочитать все регистры устройства

Пример программного чтения температуры с AHT20:

#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <stdint.h>
#include <time.h>

#define I2C_BUS "/dev/i2c-1"  // bus
#define AHT20_ADDR 0x38       // AHT20 I2C address

#define CMD_TRIGGER_MEASURE 0xAC
#define CMD_INIT 0xBE
#define CMD_SOFT_RESET 0xBA

int open_i2c_device() {
    int file = open(I2C_BUS, O_RDWR);
    if (file < 0) {
        exit(1);
    }
    if (ioctl(file, I2C_SLAVE, AHT20_ADDR) < 0) {
        exit(1);
    }
    return file;
}

void aht20_reset(int file) {
    uint8_t cmd = CMD_SOFT_RESET;
    if (write(file, &cmd, 1) != 1) {
        exit(1);
    }
    usleep(20000); 
}

void aht20_init(int file) {
    uint8_t cmd[3] = {CMD_INIT, 0x08, 0x00};
    if (write(file, cmd, 3) != 3) {
        exit(1);
    }
    usleep(10000);
}

void aht20_start_measurement(int file) {
    uint8_t cmd[3] = {CMD_TRIGGER_MEASURE, 0x33, 0x00};
    if (write(file, cmd, 3) != 3) {
        exit(1);
    }
    usleep(80000);
}

uint32_t aht20_read_raw_temperature(int file) {
    uint8_t data[6];

    if (read(file, data, 6) != 6) {
        exit(1);
    }
    uint32_t raw_temp = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5];

    return raw_temp;
}

float convert_temperature(uint32_t raw_temp) {
    return ((raw_temp * 200.0) / 1048576.0) - 50.0;
}

int main() {
    int file = open_i2c_device();

    aht20_reset(file);
    aht20_init(file);

    aht20_start_measurement(file);

    uint32_t raw_temp = aht20_read_raw_temperature(file);
    float temperature = convert_temperature(raw_temp);

    printf("Temperature: %.2f°C\n", temperature);

    close(file);
    return 0;
}
Объяснить с
CSI камера и OpenCV
GC4653
GC4653
Пример кода в Projects/OpenCV_CSI_Camera.

Для разных CSI камер требуются разные драйверы, поэтому проще всего использовать камеру, которая поддерживается в официальном образе операционной системы. В корне репозитория Buildroot через menuconfig можно выбрать камеры/сенсоры, для которых необходима поддержка. Также заявлена совместимость со всеми CSI камерами для Raspberry Pi, однако мне пока не удалось заставить работать камеру на сенсоре OV5647 (синяя Raspberry PI Camera V2). В репозитории Sipeed я открыл issue, касающееся этой камеры, и планируется вести обсуждение поддержки камеры там. В итоге все тесты будут проводится на поддерживаемой камере GC4653 от Sipeed.

Список драйверов, которые можно собрать "из коробки"
Список драйверов, которые можно собрать "из коробки"
Для подобных маломощных плат лучше использовать OpenCV Mobile - форк OpenCV, который оптимизирован под конкретную платформу (включая поддержку чтения CSI камеры, потому что на разных платформах она реализуется по-разному). Последний релиз OpenCV Mobile под LicheeRV Nano использует пины CSI камеры старой ревизии (70405) платы, поэтому чтение камеры с новых плат не работает (ревизия написана на нижней стороне платы). Я покупал плату на Aliexpress в ноябре 2024 года, и она уже была свежей 70415 ревизии.

Изменение пинаута между ревизиями
Изменение пинаута между ревизиями
Я пропатчил и пересобрал библиотеку под новую ревизию, а также отправил Pull Request. Также в библиотеку я добавил возможность получить указатель на “сырое” изображение с камеры, подробнее об этом будет написано позднее. Готовую собранную библиотеку вы можете скачать здесь. Архив с библиотекой необходимо распаковать в директорию libs. Также в примере кода в директории libs есть скрипт download.sh, который автоматически скачает и распакует библиотеку.

Иерархия файлов:

.
├── CMakeLists.txt
├── libs
│   ├── download.sh
│   └── opencv-mobile-4.10.0-licheerv-nano
├── main.cpp
└── README.md
Объяснить с
Код для чтения камеры стандартный:

#include <opencv2/core/core.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <stdio.h>
#include <chrono>


#define VIDEO_RECORD_FRAME_WIDTH 640
#define VIDEO_RECORD_FRAME_HEIGHT 640


int main()
{

	cv::VideoCapture cap;
	// cap.set(cv::CAP_PROP_FRAME_WIDTH, VIDEO_RECORD_FRAME_WIDTH);
	// cap.set(cv::CAP_PROP_FRAME_HEIGHT, VIDEO_RECORD_FRAME_HEIGHT);
	cap.open(0);

	cv::Mat bgr;

	// "Warmup" camera
	for (int i = 0; i < 5; i++) cap >> bgr;

	for (int i = 0; i < 25; i++)
	{
		std::chrono::steady_clock::time_point begin = std::chrono::steady_clock::now();
		cap >> bgr;
		std::chrono::steady_clock::time_point end = std::chrono::steady_clock::now();
		printf("Get frame - OK\n");
		double fps = 1 / std::chrono::duration<double>(end - begin).count();
		printf("%lf", fps);
		if (bgr.empty())
			break;
		cv::imwrite("captured.jpg", bgr);
	}

	cap.release();

	return 0;
}
Объяснить с
CMakeLists.txt:

cmake_minimum_required(VERSION 3.5)

project(CSIRead)
set(CMAKE_CXX_STANDARD 11)

SET(CMAKE_C_COMPILER "$ENV{COMPILER}/riscv64-unknown-linux-musl-gcc")
SET(CMAKE_CXX_COMPILER "$ENV{COMPILER}/riscv64-unknown-linux-musl-g++")
SET(CMAKE_C_LINK_EXECUTABLE "$ENV{COMPILER}/riscv64-unknown-linux-musl-ld")
set(CMAKE_SYSTEM_PROCESSOR arm)

set(OpenCV_DIR "${CMAKE_CURRENT_SOURCE_DIR}/libs/opencv-mobile-4.10.0-licheerv-nano/lib/cmake/opencv4")
find_package(OpenCV REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})

add_executable(CSIRead main.cpp)

target_link_libraries(CSIRead ${OpenCV_LIBS})
Объяснить с
Важно корректно завершать работу камеры через cap.release(), так как если этого не сделать, то без перезапуска платы камера снова не запустится.

Сборка проекта:

mkdir build
cd build
cmake ..
make
Объяснить с
Далее бинарник CSIRead нужно скопировать на плату, но перед его запуском необходимо “проинициализировать камеру”. Я пока не разобрался с этой проблемой, но для корректного чтения камеры через OpenCV Mobile после загрузки платы один раз надо запустить sensor_test (/mnt/system/usr/bin/sensor_test). И экспортировать LD_LIBRARY_PATH, если не настроили автоматический экспорт в /etc/profile:

/mnt/system/usr/bin/sensor_test
# В нём написать 255 для выхода
export LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch/tpu_sdk_libs:/root/libs_patch:/root/libs_patch/opencv
./CSIRead
Объяснить с
Видимо необходимо перенести часть кода из sensor_test в VideoCapture::open в OpenCV Mobile, чтобы взаимодействовать с камерой без таких костылей.

После запуска программа выведет FPS чтения каждого из 25 кадров, а также последний будет сохранён в captured.jpg. Чтение кадров 640x640 идёт примерно в 60 FPS.

Стрим камеры в MJPEG
GIF стрима
GIF стрима
Пример кода в Projects/MJPEGStream.

По отдельным кадрам, сохраненным на SD карту, не очень удобно взаимодействовать с камерой. А когда необходимо собирать датасет, то очень желательно видеть текущее изображение с камеры, чтобы точнее нацелить камеру и не сохранять фотографии, где необходимого объекта нет. Самый простой способ реализовать стриминг изображений с камеры - MJPEG. Принцип простой: в сетевой http поток, отправляются кадры, закодированные в JPEG. Преимущества - не очень высокая вычислительная нагрузка (по сравнению с rtsp), а также возможность смотреть MJPEG в любом современном браузере (или ffplay, vlc). Также с помощью ffmpeg можно достаточно просто записать его в mp4, чтобы в дальнейшем размечать датасет по видео, а не набору кадров.

Реализацию MJPEG я взял из этого репозитория. 

Пример его использования:

#include "MJPEGWriter.h"
#include <opencv2/opencv.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <unistd.h>
#include <signal.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>

volatile uint8_t interrupted = 0;

void interrupt_handler(int signum)
{
    printf("Signal: %d\n", signum);
    interrupted = 1;
}

int main()
{
    signal(SIGINT, interrupt_handler);

    cv::VideoCapture cap;
    cv::Mat bgr;

    cap.open(0);
    MJPEGWriter test(7777);

    cap >> bgr;
    cv::cvtColor(bgr, bgr, cv::COLOR_BGR2GRAY);

    test.write(bgr);
    test.start();

    while (!interrupted)
    {
        cap >> bgr;
        cv::cvtColor(bgr, bgr, cv::COLOR_BGR2GRAY);
        test.write(bgr);
        bgr.release();
    }

    printf("Stopping stream:\n");
    test.stop();
    cap.release();

    return 0;
}
Объяснить с
CMakeLists.txt:

cmake_minimum_required(VERSION 3.5)

project(CSIStream)
set(CMAKE_CXX_STANDARD 11)

SET(CMAKE_C_COMPILER "$ENV{COMPILER}/riscv64-unknown-linux-musl-gcc")
SET(CMAKE_CXX_COMPILER "$ENV{COMPILER}/riscv64-unknown-linux-musl-g++")
SET(CMAKE_C_LINK_EXECUTABLE "$ENV{COMPILER}/riscv64-unknown-linux-musl-ld")
set(CMAKE_SYSTEM_PROCESSOR arm)

set(OpenCV_DIR "${CMAKE_CURRENT_SOURCE_DIR}/libs/opencv-mobile-4.10.0-licheerv-nano/lib/cmake/opencv4")
find_package(OpenCV REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})

add_executable(CSIStream main.cpp MJPEGWriter.cpp)

target_link_libraries(CSIStream ${OpenCV_LIBS})
Объяснить с
Хочу обратить внимание на функцию interrupt_handler, которая обрабатывает сигнал SIGINT (Ctrl + C в терминале). Она позволяет корректно завершать работу программы, освобождая http порт и CSI камеру (очень важно, в отличии от USB камер).

В 29 строке я провожу конвертацию изображения в Ч/Б, если не нужно, то можете закомментировать, чтобы передавать цветное изображение.

Программа собирается, так же как и пример с OpenCV Mobile. В директории libs должна быть распакована OpenCV Mobile.

Открыть стрим можно в браузере или через ffplay/vlc:

ffplay http://192.168.1.21:7777
Объяснить с
192.168.1.21 замените на IP адрес вашей платы.

OTG
USB флешка и LicheeRV Nano
USB флешка и LicheeRV Nano
Type C USB порт на плате можно использовать в двух режимах: host (otg) и device. В device режиме к плате можно подключаться по ACM с компьютера, а в host (otg) режиме подключать периферию: флешки, камеры и т.д. (тот же самый otg есть и в android смартфонах, позволяющий подключать usb устройства). 

По-умолчанию порт работает в device режиме, но я подключаюсь к плате по ssh через WiFi, поэтому возможностями порта в device режиме я просто не пользуюсь, а host режим может быть полезен. Для перевода порта в host режим необходимо удалить файл /boot/usb.dev и создать /boot/usb.host. После этого перезагрузить плату:

touch /boot/usb.host
rm /boot/usb.dev
reboot
Объяснить с
Теперь через OTG переходник можно подключить, например, флешку или SSD. Наверное, можно реализовать загрузку операционной системы с SSD, хотя при этом на SD карте всё-равно должен быть U-Boot. Я таких экспериментов не проводил, поэтому не знаю насколько это легко сделать. Но на самом деле, не думаю, что в этом есть необходимость, так как ресурса хорошей SD карты должно хватить надолго, а внешний SSD лишит плату компактности.

Взаимодействие с флешкой выполняется стандартными командами:

lsusb # для проверки, что система обнаружила флешку
mkdir /mnt/test_usb # создание точки монтирования
fdisk -l # просмотр всех разделов/дисков
mount /dev/sda1 /mnt/test_usb # монтирование флешки
Объяснить с
Работа с USB флешкой
Работа с USB флешкой
Пример кода в Projects/OTGCamera.

USB-камера потребляет довольно много тока, которого USB-порт на плате не способен обеспечить. Из-за этого камера даже не запускается и не отображается в списке устройств. Чтобы решить эту проблему, ей необходимо отдельное питание. Самый простой вариант — использовать USB-хаб с дополнительным питанием.

USB камера, подключенная через хаб к LicheeRV Nano
USB камера, подключенная через хаб к LicheeRV Nano
Для считывания кадров с USB-камеры чаще всего применяется OpenCV. Однако на этой плате целесообразно использовать OpenCV Mobile, из которого, в целях оптимизации, была убрана поддержка USB (UVC) камер (но можно пересобрать с модулем UVC, при этом нужно будет внести модификации в VideoCapture, чтобы оставить поддержку CSI камеры). В Linux работа с USB-камерами (и не только) осуществляется через V4L (Video for Linux) — универсальный интерфейс, применяемый практически везде. Поэтому следующий пример кода для работы с UVC-камерами можно использовать и на других платах, таких как Luckfox Pico или Milk-V Duo. В официальном образе Buildroot, V4L уже предустановлен, так что его не нужно собирать вручную.

Чтение кадров происходит в цветовой схеме YUV (на всех дешёвых камерах). Более качественные камеры могут передавать изображения в других форматах. Но, хотелось бы обратить внимание, что считывать большие кадры c USB-камеры (хотя бы, в разрешении Full HD - 1920x1080) в 30 FPS на таких слабых платах не получится. Их можно использовать только для тестов и экспериментов, в которых высокий FPS не нужен.

Пример кода, который считывает кадры через V4L API и переводит их в OpenCV::Mat:

#include <linux/videodev2.h>
#include <opencv2/opencv.hpp>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <cstring>
#include <chrono>

#define DEBUG
#define IMAGE_WIDTH 640
#define IMAGE_HEIGHT 480
#define DEVICE "/dev/video0"

struct Buffer
{
	void *start;
	size_t length;
};
#define CLEAR(x) memset(&(x), 0, sizeof(x))

int main()
{
	const char *device = DEVICE;
	int fd = open(device, O_RDWR);
	if (fd == -1)
	{
		perror("Opening video device");
		return -1;
	}
	// Query device capabilities
	struct v4l2_capability cap;
	if (ioctl(fd, VIDIOC_QUERYCAP, &cap) == -1)
	{
		perror("Querying Capabilities");
		close(fd);
		return -1;
	}
#ifdef DEBUG
	printf("Driver: %s\nCard: %s\nVersion: %d.%d.%d", cap.driver, cap.card,
		   ((cap.version >> 16) & 0xFF), ((cap.version >> 8) & 0xFF), (cap.version & 0xFF));
#endif

	struct v4l2_format fmt;
	CLEAR(fmt);
	fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	fmt.fmt.pix.width = IMAGE_WIDTH;   // Image width
	fmt.fmt.pix.height = IMAGE_HEIGHT; // Image height
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
	fmt.fmt.pix.field = V4L2_FIELD_INTERLACED;

	if (ioctl(fd, VIDIOC_S_FMT, &fmt) == -1)
	{
		perror("Setting Pixel Format");
		close(fd);
		return -1;
	}

	struct v4l2_requestbuffers req;
	CLEAR(req);
	req.count = 1;
	req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	req.memory = V4L2_MEMORY_MMAP;

	if (ioctl(fd, VIDIOC_REQBUFS, &req) == -1)
	{
		perror("Requesting Buffer");
		close(fd);
		return -1;
	}

	// Query buffer to map memory
	struct v4l2_buffer buf;
	CLEAR(buf);
	buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	buf.memory = V4L2_MEMORY_MMAP;
	buf.index = 0;

	if (ioctl(fd, VIDIOC_QUERYBUF, &buf) == -1)
	{
		perror("Querying Buffer");
		close(fd);
		return -1;
	}

	Buffer buffer;
	buffer.length = buf.length;
	buffer.start = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, buf.m.offset);

	if (buffer.start == MAP_FAILED)
	{
		perror("Mapping Buffer");
		close(fd);
		return -1;
	}

	// Start streaming
	enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	if (ioctl(fd, VIDIOC_STREAMON, &type) == -1)
	{
		perror("Starting Stream");
		close(fd);
		return -1;
	}

	// Capture loop
	cv::Mat yuyv(IMAGE_HEIGHT, IMAGE_WIDTH, CV_8UC2, buffer.start);
	cv::Mat bgr;
	auto last = std::chrono::steady_clock::now();
	auto curr = std::chrono::steady_clock::now();
	while (true)
	{
		CLEAR(buf);
		buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
		buf.memory = V4L2_MEMORY_MMAP;

		if (ioctl(fd, VIDIOC_QBUF, &buf) == -1)
		{
			perror("Queue Buffer");
			break;
		}

		if (ioctl(fd, VIDIOC_DQBUF, &buf) == -1)
		{
			perror("Dequeue Buffer");
			break;
		}
		
		cv::cvtColor(yuyv, bgr, cv::COLOR_YUV2BGR_YUYV);
		curr = std::chrono::steady_clock::now();
		printf("Frame latency: %lf\n", std::chrono::duration<double>(curr - last).count());
		last = curr;
		// cv::imwrite("res.jpg", bgr);
	}

	return 0;
}
Объяснить с
С моей камеры этот код читает кадры 640x480 и переводит в OpenCV::Mat примерно со скоростью в 7 FPS (на LicheeRV Nano).

Docker
Производительности платы недостаточно для комфортной работы с крупными Docker-контейнерами, однако образы на базе Alpine или Ubuntu в целом запускаются, хотя и довольно медленно — порядка 5 минут. Тем не менее, проведённый эксперимент был полезен.

Установка и сборка Docker’а будет выполняться через Buildroot. Для этого в его конфиг (/workspace/buildroot/configs/cvitek_SG200X_musl_riscv64_defconfig) нужно добавить следующие пакеты:

BR2_PACKAGE_LIBSECCOMP_ARCH_SUPPORTS=y
BR2_PACKAGE_LIBSECCOMP=y
BR2_PACKAGE_CA_CERTIFICATES=y
BR2_PACKAGE_DOCKER_CLI=y
BR2_PACKAGE_DOCKER_COMPOSE=y
BR2_PACKAGE_DOCKER_ENGINE=y
BR2_PACKAGE_CONTAINERD=y
BR2_PACKAGE_RUNC=y
Объяснить с
Для корректной работы Docker также требуется поддержка CGROUPS и некоторых других параметров ядра. Дамп конфигурационного файла, с которым Docker успешно запустился, доступен здесь. Его содержимое необходимо скопировать в /workspace/linux_5.10/build/sg2002_licheervnano_sd/.config.

Docker Daemon стартует автоматически при загрузке операционной системы. Как уже было сказано, с лёгкими контейнерами работать можно, но более тяжёлые загружаются очень долго. Также стоит учитывать, что не все контейнеры поддерживают архитектуру RISC-V (например, ROS2).

Вывод: Docker запускается и работает, но производительности процессора недостаточно для его полноценного использования в реальных задачах.

FreeRTOS
В начале статьи упоминалось, что внутри SG2002 имеется отдельное ядро, которое разработчики предлагают использовать для RTOS. Оно работает на частоте 700 MHz, чего вполне достаточно для управления периферией. Таким образом, на одном кристалле можно параллельно запускать как полноценную операционную систему, так и ОСРВ.

Для данной платы существует порт FreeRTOS, который и будет использоваться в этой статье. Его исходники уже включены в официальный Buildroot-образ LicheeRV Nano (/workspace/freertos/cvitek), однако по умолчанию его сборка отключена.

Сборка и запуск
Чтобы включить сборку FreeRTOS, необходимо открыть menuconfig с общими настройками:

cd /workspace
menuconfig
Объяснить с
Затем перейти во вкладку RTOS и активировать FreeRTOS.

Включение сборки FreeRTOS
Включение сборки FreeRTOS
За сборку самого FreeRTOS и кода, который будет выполняться на втором ядре, отвечает скрипт build_cv181x.sh. Пользовательские задачи можно добавлять в файл comm_main.c (/workspace/freertos/cvitek/task/comm/src/riscv64/comm_main.c). В репозитории уже содержится достаточно обширный пример, но для теста я предлагаю заменить его на более простой код, состоящий всего из одной задачи, которая выводит "Hello, world".

Linux и FreeRTOS совместно используют отладочный UART0, поэтому оба могут выводить сообщения в один и тот же лог. Сообщения от RTOS-ядра помечены префиксом ‘RT:’.

Пример кода в Projects/FreeRTOS.

comm_main.c:

/* Standard includes. */
#include <stdio.h>
#include <stdint.h>

/* Kernel includes. */
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "mmio.h"
#include "delay.h"

/* cvitek includes. */
#include "printf.h"
#include "rtos_cmdqu.h"
#include "cvi_mailbox.h"
#include "intr_conf.h"
#include "top_reg.h"
#include "memmap.h"
#include "comm.h"
#include "cvi_spinlock.h"

//#define __DEBUG__

#ifdef __DEBUG__
#define debug_printf printf
#else
#define debug_printf(...)
#endif

/****************************************************************************
 * Function prototypes
 ****************************************************************************/
void app_task(void *param);

/****************************************************************************
 * Global parameters
 ****************************************************************************/

/* mailbox parameters */
volatile struct mailbox_set_register *mbox_reg;
volatile struct mailbox_done_register *mbox_done_reg;
volatile unsigned long *mailbox_context; // mailbox buffer context is 64 Bytess

/****************************************************************************
 * Function definitions
 ****************************************************************************/

DEFINE_CVI_SPINLOCK(mailbox_lock, SPIN_MBOX);

void app_task_demo(void *param)
{
	while (1) {
        printf("Hello RISC-V from the small core!\r\n");
	    vTaskDelay(50); // 0.25 of second (1 second 200 ticks check config)
	}
}

void main_cvirtos(void)
{
	printf("create cvi task\n");

	/* Start the tasks and timer running. */
	xTaskCreate(app_task_demo, "task_demo", 1024, NULL, 1, NULL);
	vTaskStartScheduler();

	printf("cvi task end\n");

	for (;;);
}
Объяснить с
За компиляцию comm_main.c отвечает /workspace/freertos/cvitek/task/comm/CMakeLists.txt, в который можно добавить библиотеки (например, hal или uart):

file(GLOB _SOURCES "src/${RUN_ARCH}/*.c")

if (CONFIG_FAST_IMAGE_TYPE STRGREATER "0")
add_compile_definitions(FAST_IMAGE_ENABLE)
endif()

include_directories(include)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/arch)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/common)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/kernel)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/driver/spinlock)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/driver/jenc)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/driver/rtos_cmdqu)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/driver/fast_image)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/hal/config)

include_directories(${CMAKE_INSTALL_INC_PREFIX}/hal/uart)
include_directories(${CMAKE_INSTALL_INC_PREFIX}/hal/pinmux1)


add_library(comm STATIC ${_SOURCES})
install(TARGETS comm DESTINATION lib)
Объяснить с
После инициализации платы в task/main вызывается функция main_cvirtos, где создаются задачи и запускается планировщик (vTaskStartScheduler). В целом, можно писать код непосредственно в task/main после вызова функции post_system_init, однако, чтобы отделить код инициализации ядра от пользовательского кода, рекомендуется работать с FreeRTOS в файле comm_main.c.

Пересобрать FreeRTOS можно вместе со всем образом (build_all), но это займет больше времени и потребует обновления всей системы ради одного бинарника. Гораздо проще пересобрать только FSBL (First Stage Bootloader):

build_fsbl
scp /workspace/install/soc_sg2002_licheervnano_sd/fip.bin root@192.168.1.21:/boot/fip.bin
Объяснить с
После этого необходимо просто перезагрузить плату. Теперь в логах загрузки (UART0) должно появиться что-то подобное (у меня выводится дополнительная отладочная информация):

Сначала запускается RTOS ядро, а затем Linux ядро
Сначала запускается RTOS ядро, а затем Linux ядро
В итоге второе ядро будет “спамить” сообщениями в UART0:

200 тиков - 1 секунда, delay в 50 тиков -> 4 раза за секунду
200 тиков - 1 секунда, delay в 50 тиков -> 4 раза за секунду
Примеры
Для дальнейших примеров в репозитории представлен только код задачи (app_task_demo) и необходимые includ’ы. Основной код базируется на примере, приведенном выше (hello, world). Также рекомендую ознакомиться с готовыми библиотеки для работы с периферией, которые находятся в директории hal (./freertos/cvitek/hal) исходников FreeRTOS.

GPIO
Пример кода в Projects/FreeRTOS.

Для удобства управления GPIO пинами в пример были добавлены функции pinMode, writePin, readPin, которые упрощают работу с пинами.

Необходимые дефайны:

#define TOP_BASE 0x03000000

// GPIO Register base
#define XGPIO (TOP_BASE + 0x20000)
// GPIO Port offset
#define GPIO_SIZE 0x1000

// Port A external port register (read from here when configured as input)
#define GPIO_EXT_PORTA 0x50
// Port A data register
#define GPIO_SWPORTA_DR 0x00
// Port A data direction register
#define GPIO_SWPORTA_DDR 0x04

#define PORT_A 0
#define PORT_B 1
#define PORT_C 2
#define PORT_D 3

#define GPIO_INPUT 0
#define GPIO_OUTPUT 1
#define GPIO_LOW 0
#define GPIO_HIGH 1

#define PINMUX_BASE (TOP_BASE + 0x1000)
#define FMUX_GPIO_FUNCSEL_BASE 0xd4
#define FMUX_GPIO_FUNCSEL_MASK 0x7
#define FMUX_GPIO_FUNCSEL_GPIOC 3

#define FUNCSEL(port, pin) (FMUX_GPIO_FUNCSEL_BASE + port * 0x20u + pin)
#define BIT(x) (1UL << (x))
Объяснить с
Имплементация функций управления пинами:

void pinMode(uint8_t port, uint8_t pin, uint8_t value)
{
	mmio_clrsetbits_32(XGPIO + GPIO_SIZE * port + GPIO_SWPORTA_DDR,
			   BIT(pin), // erase Bit of PIN_NO( LED )
			   BIT(pin) // set Bit of PIN_NO( LED )
	);
}

void writePin(uint8_t port, uint8_t pin, uint8_t value)
{
	uint32_t base_addr = XGPIO + GPIO_SIZE * port;

	uint32_t reg_val = mmio_read_32(base_addr + GPIO_SWPORTA_DR);
	reg_val = (value == GPIO_HIGH ? (reg_val | BIT(pin)) :
					(reg_val & (~BIT(pin))));
	mmio_write_32(base_addr + GPIO_SWPORTA_DR, reg_val);
}

uint8_t readPin(uint8_t port, uint8_t pin)
{
	uint32_t base_addr = XGPIO + GPIO_SIZE * port;
	uint32_t reg_val = 0;

	// let's find out if this pin is configured as GPIO and INPUT or OUTPUT
	uint32_t func = mmio_read_32(PINMUX_BASE + FUNCSEL(port, pin));
	if (func == FMUX_GPIO_FUNCSEL_GPIOC) {
		uint32_t dir = mmio_read_32(base_addr + GPIO_SWPORTA_DDR);
		if (dir & BIT(pin)) {
			reg_val = mmio_read_32(GPIO_SWPORTA_DR + base_addr);
		} else {
			reg_val = mmio_read_32(GPIO_EXT_PORTA + base_addr);
		}
	} else {
		printf("%d not configured as GPIO\n", pin);
	}

	return ((reg_val >> pin) & 1);
}
Объяснить с
Управление пином из FreeRTOS задачи:

uint8_t PIN = 15; // Addr 0x0300103C

uint8_t PORT = PORT_A;
mmio_write_32(0x0300103C, 0x3); // GPIOA 15 GPIO_MODE
pinMode(PORT, PIN, GPIO_OUTPUT);

printf("Port %d, pin %d\n", PORT, PIN);

while (1) {
    writePin(PORT, PIN, GPIO_HIGH);
    vTaskDelay(50);

    writePin(PORT, PIN, GPIO_LOW);
    vTaskDelay(50);
}
Объяснить с
Стоит обратить внимание на конфигурацию мультиплексора, которая делается так же, как и в U-Boot, через mmio_write_32. Регистр и необходимое значение для пина определяется по даташиту, как описано выше, в разделе Linux-GPIO.

UART
Пример кода в Projects/FreeRTOS.

Код задачи:

// INCLUDES
#include "hal_uart_dw.h"
/*
...
*/

// TASK source
void app_task_demo(void *param)
{
	// HAL UART1 test

	mmio_write_32(0x03001064, 0x6); // TX; UART1 on pins 18,19
	mmio_write_32(0x03001068, 0x6); // RX 0x03001068 0x6

	static struct dw_regs *uart = 0;
	int baudrate = 115200, uart_clock = 25 * 1000 * 1000;
	int divisor = (uart_clock + 8 * baudrate) / (16 * baudrate);

	uart = (struct dw_regs *)UART1_BASE;

	uart->lcr = uart->lcr | UART_LCR_DLAB | UART_LCR_8N1;
	uart->dll = divisor & 0xff;
	uart->dlm = (divisor >> 8) & 0xff;
	uart->lcr = uart->lcr & (~UART_LCR_DLAB);

	uart->ier = 0;
	uart->mcr = UART_MCRVAL;
	uart->fcr = UART_FCR_DEFVAL;

	uart->lcr = 3;

	while (1) {
		for (int i = 0; i < 10; i++) {
			while (!(uart->lsr & UART_LSR_THRE))
				;
			uart->rbr = 'Z';
		}
		vTaskDelay(200); // 1 second

	}
}
Объяснить с
Сначала настраивается мультиплексор для UART1 на пинах A18 (RX) и A19 (TX), после чего инициализируется UART1 на рабочую скорость 115200 бод. Инициализацию желательно вынести в отдельную функцию, но чтобы не усложнять пример, весь код находится внутри функции одной задачи. Также для более простой инициализации и использования UART вы можете использовать готовые функции hal_uart_init, hal_uart_putc, hal_uart_getc из файла hal_uart_dw.c.

UART1 TX
UART1 TX
Связь с другими ядрами
Пример Linux-кода в Projects/FreeRTOS.
Пример RTOS-кода в Projects/FreeRTOS.

Все ядра в SoC'е поддерживают Intel Mailbox. В данной статье будет рассмотрена связь между Linux ядром и RTOS, хотя также существует возможность реализовать связь между ядром 8051 и Linux/RTOS.

Взаимодействие с RTOS со стороны Linux ядра реализуется следующим образом:

#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>

enum SYSTEM_CMD_TYPE {
	CMDQU_SEND = 1,
	CMDQU_REQUEST,
	CMDQU_REQUEST_FREE,
	CMDQU_SEND_WAIT,
	CMDQU_SEND_WAKEUP,
};

enum IP_TYPE {
	IP_ISP = 0,
	IP_VCODEC,
	IP_VIP,
	IP_VI,
	IP_RGN,
	IP_AUDIO,
	IP_SYSTEM,
	IP_CAMERA,
	IP_LIMIT,
};


#define RTOS_CMDQU_DEV_NAME "/dev/cvi-rtos-cmdqu"
#define RTOS_CMDQU_SEND                         _IOW('r', CMDQU_SEND, unsigned long)
#define RTOS_CMDQU_SEND_WAIT                    _IOW('r', CMDQU_SEND_WAIT, unsigned long)
#define RTOS_CMDQU_SEND_WAKEUP                  _IOW('r', CMDQU_SEND_WAKEUP, unsigned long)

enum SYS_CMD_ID {
	SYS_CMD_INFO_LINUX = 0x50
};


enum DUO_LED_STATUS {
	DUO_LED_ON	= 0x02,
	DUO_LED_OFF,
    DUO_LED_DONE,
};

struct valid_t {
	unsigned char linux_valid;
	unsigned char rtos_valid;
} __attribute__((packed));

typedef union resv_t {
	struct valid_t valid;
	unsigned short mstime; // 0 : noblock, -1 : block infinite
} resv_t;

typedef struct cmdqu_t cmdqu_t;
/* cmdqu size should be 8 bytes because of mailbox buffer size */
struct cmdqu_t {
	unsigned char ip_id;
	unsigned char cmd_id : 7;
	unsigned char block : 1;
	union resv_t resv;
	unsigned int  param_ptr;
} __attribute__((packed)) __attribute__((aligned(0x8)));

int main()
{
    int ret = 0;
    int fd = open(RTOS_CMDQU_DEV_NAME, O_RDWR);
    if(fd <= 0)
    {
        printf("open failed! fd = %d\n", fd);
        return 0;
    }

    struct cmdqu_t cmd = {0};
    cmd.ip_id = IP_SYSTEM;
    cmd.cmd_id = SYS_CMD_INFO_LINUX;
    cmd.resv.mstime = 100;

    cmd.param_ptr = 0x2;

    ret = ioctl(fd , RTOS_CMDQU_SEND_WAIT, &cmd);
    if(ret < 0)
    {
        printf("ioctl error!\n");
        close(fd);
    }
    printf("%d", cmd.param_ptr); // 0x7 - response from RTOS

    
    // Measure latency on RTOS core
    // for (int i = 0; i < 100; i++){
    //     ret = ioctl(fd , RTOS_CMDQU_SEND, &cmd);
    //     if(ret < 0)
    //     {
    //         printf("ioctl error!\n");
    //         close(fd);
    //     }
    //     // printf("%d\n", cmd.resv);
    //     usleep(16000);
    // }
    

    close(fd);
    return 0;
}
Объяснить с
Структура cmdqu_t описывает сообщение, передаваемое между ядрами. Поле IP_TYPE определяет обработчик сообщений: например, IP_SYSTEM обрабатывается нашей задачей внутри FreeRTOS, а остальные могут использоваться для взаимодействия с ISP, аудиосистемой и другими интерфейсами. Подробнее это можно изучить в полном примере задачи для FreeRTOS от Sipeed.

Существует два способа отправки сообщений по Mailbox на FreeRTOS ядро:

RTOS_CMDQU_SEND - отправка без ожидания ответа

RTOS_CMDQU_SEND_WAIT - отправка с ожиданием ответа от ядра

В текущем примере рассматривается второй вариант, так как он позволяет реализовать двустороннюю связь между ядрами. При этом связь инициируется со стороны Linux ядра, однако RTOS ядро также может в любой момент отправить сообщение на Linux.

В результате Linux клиент отправит на RTOS ядро команду с параметрами:

ip_id = IP_SYSTEM

cmd_id = SYS_CMD_INFO_LINUX

param_ptr = 0x2

После отправки он будет ожидать ответа от RTOS ядра, которое выведет отладочные сообщения в UART0 и отправит ответное сообщение с param_ptr = 0x7.

Список команд описан в enum SYS_CMD_ID. Его определения в коде Linux клиента и FreeRTOS должны совпадать, чтобы команды корректно обрабатывались. В качестве примера в SYS_CMD_ID содержится единственная команда - SYS_CMD_INFO_LINUX.

Код FreeRTOS задачи в файле comm_main.c:

/* Standard includes. */
#include <stdio.h>

/* Kernel includes. */
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "mmio.h"
#include "delay.h"

/* cvitek includes. */
#include "printf.h"
#include "rtos_cmdqu.h"
#include "fast_image.h"
#include "cvi_mailbox.h"
#include "intr_conf.h"
#include "top_reg.h"
#include "memmap.h"

#include "comm.h"
#include "cvi_spinlock.h"

//#define __DEBUG__

#ifdef __DEBUG__
#define debug_printf printf
#else
#define debug_printf(...)
#endif

extern struct transfer_config_t transfer_config;
struct trace_snapshot_t snapshot;

typedef struct _TASK_CTX_S {
	char        name[32];
	u16         stack_size;
	UBaseType_t priority;
	void (*runTask)(void *pvParameters);
	u8            queLength;
	QueueHandle_t queHandle;
} TASK_CTX_S;

long long lastTick = 0;

/****************************************************************************
 * Function prototypes
 ****************************************************************************/
void prvQueueISR(void);
void prvCmdQuRunTask(void *pvParameters);

/****************************************************************************
 * Global parameters
 ****************************************************************************/
TASK_CTX_S gTaskCtx[E_QUEUE_MAX] = {
	{
		.name = "ISP",
		.stack_size = configMINIMAL_STACK_SIZE * 8,
		.priority = tskIDLE_PRIORITY + 3,
		.runTask = NULL,
		.queLength = 1,
		.queHandle = NULL,
	},
	{
		.name = "VCODEC",
		.stack_size = configMINIMAL_STACK_SIZE,
		.priority = tskIDLE_PRIORITY + 3,
		.runTask = NULL,
		.queLength = 1,
		.queHandle = NULL,
	},
	{
		.name = "VI",
		.stack_size = configMINIMAL_STACK_SIZE,
		.priority = tskIDLE_PRIORITY + 3,
		.runTask = NULL,
		.queLength = 1,
		.queHandle = NULL,
	},
	{
		.name = "CAMERA",
		.stack_size = configMINIMAL_STACK_SIZE,
		.priority = tskIDLE_PRIORITY + 3,
		.runTask = NULL,
		.queLength = 1,
		.queHandle = NULL,
	},
	{
		.name = "RGN",
		.stack_size = configMINIMAL_STACK_SIZE,
		.priority = tskIDLE_PRIORITY + 3,
		.runTask = prvRGNRunTask,
		.queLength = 10,
		.queHandle = NULL,
	},
	{
		.name = "CMDQU",
		.stack_size = configMINIMAL_STACK_SIZE,
		.priority = tskIDLE_PRIORITY + 5,
		.runTask = prvCmdQuRunTask,
		.queLength = 30,
		.queHandle = NULL,
	},
	{
		.name = "AUDIO",
		.stack_size = configMINIMAL_STACK_SIZE*15,
		.priority = tskIDLE_PRIORITY + 3,
		.runTask = prvAudioRunTask,
		.queLength = 10,
		.queHandle = NULL,
	},
};

volatile struct mailbox_set_register *mbox_reg;
volatile struct mailbox_done_register *mbox_done_reg;
volatile unsigned long *mailbox_context; // mailbox buffer context is 64 Bytess

/****************************************************************************
 * Function definitions
 ****************************************************************************/
QueueHandle_t main_GetMODHandle(QUEUE_HANDLE_E handle_idx)
{
	if (handle_idx >= E_QUEUE_MAX)
		return NULL;

	return gTaskCtx[handle_idx].queHandle;
}

void main_create_tasks(void)
{
	u8 i = 0;
	// u8 _idx = 5;
	// xTaskCreate(gTaskCtx[_idx].runTask, gTaskCtx[_idx].name, gTaskCtx[_idx].stack_size, \
	// 		    NULL, gTaskCtx[_idx].priority, NULL); \

#define TASK_INIT(_idx) \
do { \
	gTaskCtx[_idx].queHandle = xQueueCreate(gTaskCtx[_idx].queLength, sizeof(cmdqu_t)); \
	if (gTaskCtx[_idx].queHandle != NULL && gTaskCtx[_idx].runTask != NULL) { \
		xTaskCreate(gTaskCtx[_idx].runTask, gTaskCtx[_idx].name, gTaskCtx[_idx].stack_size, \
			    NULL, gTaskCtx[_idx].priority, NULL); printf("IND: %d\n", _idx); \
	} \
} while(0)

	for (; i < ARRAY_SIZE(gTaskCtx); i++) {
		TASK_INIT(i);
	}
}

DEFINE_CVI_SPINLOCK(mailbox_lock, SPIN_MBOX);

void main_cvirtos(void)
{
	printf("create cvi task\n");

	request_irq(MBOX_INT_C906_2ND, prvQueueISR, 0, "mailbox", (void *)0);
	main_create_tasks();

	/* Start the tasks and timer running. */
	vTaskStartScheduler();

    for (;;);
}

void prvCmdQuRunTask(void *pvParameters)
{
	(void)pvParameters;

	cmdqu_t rtos_cmdq;
	cmdqu_t *cmdq;
	cmdqu_t *rtos_cmdqu_t;
	static int stop_ip = 0;
	int ret = 0;
	int flags;
	int valid;
	int send_to_cpu = SEND_TO_CPU1;

	unsigned int reg_base = MAILBOX_REG_BASE;

	/* set mcu_status to type1 running*/
	transfer_config.mcu_status = MCU_STATUS_RTOS_T1_RUNNING;

	if (transfer_config.conf_magic == C906_MAGIC_HEADER)
		send_to_cpu = SEND_TO_CPU1;
	else if (transfer_config.conf_magic == CA53_MAGIC_HEADER)
		send_to_cpu = SEND_TO_CPU0;
	/* to compatible code with linux side */
	cmdq = &rtos_cmdq;
	mbox_reg = (struct mailbox_set_register *) reg_base;
	mbox_done_reg = (struct mailbox_done_register *) (reg_base + 2);
	mailbox_context = (unsigned long *) (MAILBOX_REG_BUFF);

	cvi_spinlock_init();

	for (;;) {
		xQueueReceive(gTaskCtx[E_QUEUE_CMDQU].queHandle, &rtos_cmdq, portMAX_DELAY);

		switch (rtos_cmdq.cmd_id) {
			
			case SYS_CMD_INFO_LINUX:
				/* used to send command to linux*/
				rtos_cmdqu_t = (cmdqu_t *) mailbox_context;
				long long currTick = xTaskGetTickCount();

				printf("Elapsed: %d\n", currTick - lastTick);
				lastTick = currTick;

				rtos_cmdq.cmd_id = SYS_CMD_INFO_LINUX;
				
				rtos_cmdq.param_ptr = 0x7;
				rtos_cmdq.resv.valid.rtos_valid = 1;
				rtos_cmdq.resv.valid.linux_valid = 0;



				debug_printf("ip_id=%d cmd_id=%d param_ptr=%x\n", cmdq->ip_id, cmdq->cmd_id, (unsigned int)cmdq->param_ptr);
				debug_printf("mailbox_context = %x\n", mailbox_context);
				debug_printf("linux_cmdqu_t = %x\n", rtos_cmdqu_t);
				debug_printf("cmdq->ip_id = %d\n", cmdq->ip_id);
				debug_printf("cmdq->cmd_id = %d\n", cmdq->cmd_id);
				debug_printf("cmdq->block = %d\n", cmdq->block);
				debug_printf("cmdq->para_ptr = %x\n", cmdq->param_ptr);

				drv_spin_lock_irqsave(&mailbox_lock, flags);
				if (flags == MAILBOX_LOCK_FAILED) {
					printf("[%s][%d] drv_spin_lock_irqsave failed! ip_id = %d , cmd_id = %d\n" , cmdq->ip_id , cmdq->cmd_id);
					break;
				}

				for (valid = 0; valid < MAILBOX_MAX_NUM; valid++) {
					if (rtos_cmdqu_t->resv.valid.linux_valid == 0 && rtos_cmdqu_t->resv.valid.rtos_valid == 0) {
						// mailbox buffer context is 4 bytes write access
						int *ptr = (int *)rtos_cmdqu_t;

						cmdq->resv.valid.rtos_valid = 1;
						*ptr = ((cmdq->ip_id << 0) | (cmdq->cmd_id << 8) | (cmdq->block << 15) |
								(cmdq->resv.valid.linux_valid << 16) |
								(cmdq->resv.valid.rtos_valid << 24));
						rtos_cmdqu_t->param_ptr = cmdq->param_ptr;
						printf("rtos_cmdqu_t->linux_valid = %d\n", rtos_cmdqu_t->resv.valid.linux_valid);
						debug_printf("rtos_cmdqu_t->rtos_valid = %d\n", rtos_cmdqu_t->resv.valid.rtos_valid);
						debug_printf("rtos_cmdqu_t->ip_id =%x %d\n", &rtos_cmdqu_t->ip_id, rtos_cmdqu_t->ip_id);
						debug_printf("rtos_cmdqu_t->cmd_id = %d\n", rtos_cmdqu_t->cmd_id);
						debug_printf("rtos_cmdqu_t->block = %d\n", rtos_cmdqu_t->block);
						printf("rtos_cmdqu_t->param_ptr addr=%x %x\n", &rtos_cmdqu_t->param_ptr, rtos_cmdqu_t->param_ptr);
						printf("*ptr = %x\n", *ptr);
						// clear mailbox
						mbox_reg->cpu_mbox_set[send_to_cpu].cpu_mbox_int_clr.mbox_int_clr = (1 << valid);
						// trigger mailbox valid to rtos
						mbox_reg->cpu_mbox_en[send_to_cpu].mbox_info |= (1 << valid);
						mbox_reg->mbox_set.mbox_set = (1 << valid);
						break;
					}
					rtos_cmdqu_t++;
				}
				drv_spin_unlock_irqrestore(&mailbox_lock, flags);
				if (valid >= MAILBOX_MAX_NUM) {
				    printf("No valid mailbox is available\n");
				    return -1;
				}
				break;
		}
	}
}

void prvQueueISR(void)
{
	printf("prvQueueISR\n");

	unsigned char set_val;
//	unsigned char done_val;
	unsigned char valid_val;
	int i;
	cmdqu_t *cmdq;
	BaseType_t YieldRequired = pdFALSE;

	set_val = mbox_reg->cpu_mbox_set[RECEIVE_CPU].cpu_mbox_int_int.mbox_int;
	/* Now, we do not implement info back feature */
	// done_val = mbox_done_reg->cpu_mbox_done[RECEIVE_CPU].cpu_mbox_int_int.mbox_int;

	if (set_val) {
		for(i = 0; i < MAILBOX_MAX_NUM; i++) {
			valid_val = set_val  & (1 << i);

			if (valid_val) {
				printf("RX\n");
				cmdqu_t rtos_cmdq;
				cmdq = (cmdqu_t *)(mailbox_context) + i;

				debug_printf("mailbox_context =%x\n", mailbox_context);
				debug_printf("sizeof mailbox_context =%x\n", sizeof(cmdqu_t));
				/* mailbox buffer context is send from linux, clear mailbox interrupt */
				mbox_reg->cpu_mbox_set[RECEIVE_CPU].cpu_mbox_int_clr.mbox_int_clr = valid_val;
				// need to disable enable bit
				mbox_reg->cpu_mbox_en[RECEIVE_CPU].mbox_info &= ~valid_val;

				// copy cmdq context (8 bytes) to buffer ASAP
				*((unsigned long *) &rtos_cmdq) = *((unsigned long *)cmdq);
				/* need to clear mailbox interrupt before clear mailbox buffer */
				*((unsigned long*) cmdq) = 0;

				/* mailbox buffer context is send from linux*/
				if (rtos_cmdq.resv.valid.linux_valid == 1) {
					debug_printf("cmdq=%x\n", cmdq);
					debug_printf("cmdq->ip_id =%d\n", rtos_cmdq.ip_id);
					debug_printf("cmdq->cmd_id =%d\n", rtos_cmdq.cmd_id);
					debug_printf("cmdq->param_ptr =%x\n", rtos_cmdq.param_ptr);
					debug_printf("cmdq->block =%x\n", rtos_cmdq.block);
					debug_printf("cmdq->linux_valid =%d\n", rtos_cmdq.resv.valid.linux_valid);
					debug_printf("cmdq->rtos_valid =%x\n", rtos_cmdq.resv.valid.rtos_valid);
					switch (rtos_cmdq.ip_id) {
					case IP_SYSTEM:
						xQueueSendFromISR(gTaskCtx[E_QUEUE_CMDQU].queHandle, &rtos_cmdq, &YieldRequired);
						break;
					default:
						printf("unknown ip_id =%d cmd_id=%d\n", rtos_cmdq.ip_id, rtos_cmdq.cmd_id);
						break;
					}
					portYIELD_FROM_ISR(YieldRequired);
				} else
					printf("rtos cmdq is not valid %d, ip=%d , cmd=%d\n",
						rtos_cmdq.resv.valid.rtos_valid, rtos_cmdq.ip_id, rtos_cmdq.cmd_id);
			}
		}
	}
}
Объяснить с
Новые сообщения от Mailbox обрабатываются через прерывание коллбэком prvQueueISR:

request_irq(MBOX_INT_C906_2ND, prvQueueISR, 0, "mailbox", (void *)0);
Объяснить с
Сообщения с ip_type == IP_SYSTEM обрабатываются задачей под названием CMDQU и функцией prvCmdQuRunTask.

Конфигурации enum IP_TYPE, SYS_CMD_ID, SYSTEM_CMD_TYPE описываются в файле rtos_cmdqu.h (./freertos/cvitek/driver/rtos_cmdqu/include/rtos_cmdqu.h) и должны совпадать с описанием в Linux клиенте.

Файл rtos_cmdqu.h:

#ifndef __RTOS_COMMAND_QUEUE__
#define __RTOS_COMMAND_QUEUE__

#ifdef __linux__
#include <linux/kernel.h>
#endif

#define NR_SYSTEM_CMD           20
#define NR_RTOS_CMD            127
#define NR_RTOS_IP        IP_LIMIT

enum IP_TYPE {
	IP_ISP = 0,
	IP_VCODEC,
	IP_VIP,
	IP_VI,
	IP_RGN,
	IP_AUDIO,
	IP_SYSTEM,
	IP_CAMERA,
	IP_LIMIT,
};

enum SYS_CMD_ID {
	SYS_CMD_INFO_LINUX = 0x50
	
};

struct valid_t {
	unsigned char linux_valid;
	unsigned char rtos_valid;
} __attribute__((packed));

typedef union resv_t {
	struct valid_t valid;
	unsigned short mstime; // 0 : noblock, -1 : block infinite
} resv_t;

typedef struct cmdqu_t cmdqu_t;
/* cmdqu size should be 8 bytes because of mailbox buffer size */
struct cmdqu_t {
	unsigned char ip_id;
	unsigned char cmd_id : 7;
	unsigned char block : 1;
	union resv_t resv;
	unsigned int  param_ptr;
} __attribute__((packed)) __attribute__((aligned(0x8)));

#ifdef __linux__
/* keep those commands for ioctl system used */
enum SYSTEM_CMD_TYPE {
	CMDQU_SEND = 1,
	CMDQU_REQUEST,
	CMDQU_REQUEST_FREE,
	CMDQU_SEND_WAIT,
	CMDQU_SEND_WAKEUP,
	CMDQU_SYSTEM_LIMIT = NR_SYSTEM_CMD,
};

#define RTOS_CMDQU_DEV_NAME "cvi-rtos-cmdqu"
#define RTOS_CMDQU_SEND                         _IOW('r', CMDQU_SEND, unsigned long)
#define RTOS_CMDQU_REQUEST                      _IOW('r', CMDQU_REQUEST, unsigned long)
#define RTOS_CMDQU_REQUEST_FREE                 _IOW('r', CMDQU_REQUEST_FREE, unsigned long)
#define RTOS_CMDQU_SEND_WAIT                    _IOW('r', CMDQU_SEND_WAIT, unsigned long)
#define RTOS_CMDQU_SEND_WAKEUP                  _IOW('r', CMDQU_SEND_WAKEUP, unsigned long)

int rtos_cmdqu_send(cmdqu_t *cmdq);
int rtos_cmdqu_send_wait(cmdqu_t *cmdq, int wait_cmd_id);
int request_rtos_irq(unsigned char ip_id, void *handler, const char *devname, void *dev_id);
int free_rtos_irq(unsigned char ip_id);

#endif // end of __linux__

#endif  // end of __RTOS_COMMAND_QUEUE__
Объяснить с
После сборки FreeRTOS и обновления его на плате, можно проверить связь между ядрами, запустив Linux клиент. 

Для отладки работы Mailbox на стороне Linux ядра можно установить уровень логирования на 8, чтобы в dmesg отображались логи Mailbox драйвера:

echo 8 > /proc/sys/kernel/printk
Объяснить с
В итоге в UART0 будут выведены сообщения о получении RTOS ядром сообщения от Linux ядра, а Mailbox клиент на Linux выведет param_ptr, равный 0x7. Это простой пример, который ничего полезного не делает, но его достаточно, для последующей реализации более сложного протокола связи между ядрами.

NPU и Yolo
Детекция кастомной моделью 320x320 YOLOv11
Детекция кастомной моделью 320x320 YOLOv11
NPU (Neural Processing Unit) — это специализированный процессор, предназначенный для эффективного выполнения вычислений, связанных с нейросетями. В отличие от CPU и GPU, которые могут выполнять широкий спектр задач, NPU оптимизирован специально для ускорения инференса нейронных сетей.

Преимущества использования NPU:

Высокая производительность — специализированная архитектура позволяет обрабатывать нейросетевые модели с минимальными задержками.

Низкое энергопотребление — в отличие от GPU, который требует значительного количества энергии, NPU выполняет вычисления более энергоэффективно.

Минимальное тепловыделение — благодаря оптимизированному управлению ресурсами, NPU выделяет меньше тепла, что делает его идеальным для встраиваемых систем и мобильных устройств.

Оптимизация для edge-устройств — NPU часто используется в IoT-устройствах, робототехнике и других системах, где требуется автономная работа и ограниченные аппаратные ресурсы.

В этом разделе будет продемонстрировано решение задачи детекции объектов в реальном времени с использованием YOLOv8 и YOLOv11 на NPU. Благодаря аппаратному ускорению, инференс будет выполняться быстро и эффективно.

Аналитика
Пример кода в Projects/Yolo_Benchmark.

Для сравнения производительности различных моделей YOLO был написан отдельная программа бенчмарка. Она измеряет скорость инференса каждой модели на изображениях из заданной директории.

В начале статьи был приведён график энергопотребления платы во время инференса, но только для YOLOv8n. Это связано с тем, что сложность модели не оказывает значительного влияния на энергопотребление, особенно с учётом низкой точности USB-тестера.

Для ускорения инференса на NPU применяется квантизация — уменьшение разрядности весов модели. NPU в SG2002 поддерживает работу только с весами двух разрядностей: INT8 и BF16.

INT8 обеспечивает максимальную производительность — до 1 TOPS.

BF16 даёт более высокое качество, но с меньшей скоростью работы — около 0.5 TOPS.

Однако при использовании YOLO с BF16 возникли определённые сложности, поэтому в статье рассматривается только вариант с INT8.

Ниже представлена сводная таблица, содержащая результаты измерений скорости инференса для различных версий моделей YOLO, датасетов и размеров входного изображения.

YOLOv8 INT8

Модель

COCO (128): FPS
640x640

COCO (128): FPS
320x320

2 класса: FPS 640x640

2 класса: FPS 320x320

yolov8n

18.1

70.2

25.2

82.4

yolov8s

8.3

31.1

9.6

34.7

yolov8m

3.4

13.4

3.6

14.0

YOLOv11 INT8

Модель

COCO (128): FPS
640x640

COCO (128): FPS
320x320

2 класса: FPS 640x640

2 класса: FPS 320x320

yolov11n

19.0

74.8

26.9

100.2

yolov11s

8.9

35.1

10.3

40.2

yolov11m

2.3

12.3

2.4

12.7

Графики для сравнения YOLOv11 и YOLOv8:

Графики инференса на разных моделях и датасетах
Графики инференса на разных моделях и датасетах
Гистограммы
Гистограммы
Веса COCO моделей:

Модель

Вес

yolov8n_coco_640_int8

3.4 Мб

yolov8s_coco_640_int8

12.1 Мб

yolov8m_coco_640_int8

29.2 Мб

yolov8n_coco_320_int8

3.2 Мб

yolov8s_coco_320_int8

11.1 Мб

yolov8m_coco_320_int8

25.9 Мб

yolov11n_coco_640_int8

3 Мб

yolov11s_coco_640_int8

10.9 Мб

yolov11m_coco_640_int8

25.8 Мб

yolov11n_coco_320_int8

2.7 Мб

yolov11s_coco_320_int8

9.6 Мб

yolov11m_coco_320_int8

21.2 Мб


Из бенчмарка явно видно 2 факта:

Скорость инференса связана с размером входных изображений обратно пропорционально (примерно, но не идеально линейно).

Количество детектируемых моделью классов достаточно сильно влияет на скорость инференса для N и S моделей.

В предыдущей статье о Luckfox Pico я также измерял метрику mAP для моделей, обученных на датасете COCO, но только на выборке из 128 изображений. Однако этого оказалось недостаточно для объективной оценки снижения точности после квантизации модели. В этой статье измерение качества работы модели будет проводиться только на кастомной модели.

Для быстрого теста вы можете использовать COCO-модель YOLOv8n (640x640), доступную здесь, а бинарник для инференса - здесь. Пример картинки с правильными размерами для детекции.

Кроме того, для работы с моделью YOLOv11 не требуется вносить изменения в код экспорта, конвертации или инференса.

Код бенчмарка:

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <chrono>
#include <functional>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#include "core/cvi_tdl_types_mem_internal.h"
#include "core/utils/vpss_helper.h"
#include "cvi_tdl.h"
#include "cvi_tdl_media.h"
#include <dirent.h>

#define MODEL_SCALE 0.0039216
#define MODEL_MEAN 0.0
#define MODEL_THRESH 0.5
#define MODEL_NMS_THRESH 0.5

#define READ_BUFF 512

typedef struct
{
    char * model_path;
    int classes;
    char * test_images_path;
} Model;

CVI_S32 init_param(const cvitdl_handle_t tdl_handle, int class_cnt)
{
    // setup preprocess
    YoloPreParam preprocess_cfg =
        CVI_TDL_Get_YOLO_Preparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION);

    for (int i = 0; i < 3; i++)
    {
        printf("asign val %d \n", i);
        preprocess_cfg.factor[i] = MODEL_SCALE;
        preprocess_cfg.mean[i] = MODEL_MEAN;
    }
    preprocess_cfg.format = PIXEL_FORMAT_RGB_888_PLANAR;

    printf("setup yolov8 param \n");
    CVI_S32 ret = CVI_TDL_Set_YOLO_Preparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION,
                                            preprocess_cfg);
    if (ret != CVI_SUCCESS)
    {
        printf("Can not set yolov8 preprocess parameters %#x\n", ret);
        return ret;
    }

    // setup yolo algorithm preprocess
    YoloAlgParam yolov8_param =
        CVI_TDL_Get_YOLO_Algparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION);
    yolov8_param.cls = class_cnt;

    printf("setup yolov8 algorithm param \n");
    ret =
        CVI_TDL_Set_YOLO_Algparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, yolov8_param);
    if (ret != CVI_SUCCESS)
    {
        printf("Can not set yolov8 algorithm parameters %#x\n", ret);
        return ret;
    }

    // set theshold
    CVI_TDL_SetModelThreshold(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, MODEL_THRESH);
    CVI_TDL_SetModelNmsThreshold(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, MODEL_NMS_THRESH);

    printf("yolov8 algorithm parameters setup success!\n");
    return ret;
}

int main(int argc, char *argv[])
{
    int vpssgrp_width = 1920;
    int vpssgrp_height = 1080;
    CVI_S32 ret = MMF_INIT_HELPER2(vpssgrp_width, vpssgrp_height, PIXEL_FORMAT_RGB_888, 1,
                                   vpssgrp_width, vpssgrp_height, PIXEL_FORMAT_RGB_888, 1);
    if (ret != CVI_TDL_SUCCESS) { return ret; }

    cvitdl_handle_t tdl_handle = NULL;
    ret = CVI_TDL_CreateHandle(&tdl_handle);
    if (ret != CVI_SUCCESS) {return ret;}

    imgprocess_t img_handle;
    CVI_TDL_Create_ImageProcessor(&img_handle);
    

    char filename[] = "config.txt";
    char buffer[READ_BUFF];
    FILE *fp = fopen(filename, "r");
    if (fp)
    {
        while ((fgets(buffer, READ_BUFF, fp)) != NULL)
        {
            if (buffer[0] != '#'){
                char* token = strtok(buffer, " ");
                int index = 0;
                Model tmp = {filename, 2, filename};
                while (token != NULL) {

                    switch (index)
                    {
                        case 0:
                            tmp.model_path = token;
                            break;
                        case 1:
                            tmp.classes = atoi(token);
                            break;
                        case 2:
                            token[strlen(token) - 1] = '\0';
                            tmp.test_images_path = token;
                    }
                    token = strtok(NULL, " ");
                    index++;
                }
                printf("%s:%d:%s\n", tmp.model_path, tmp.classes, tmp.test_images_path);
                ret = init_param(tdl_handle, tmp.classes);
                ret = CVI_TDL_OpenModel(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, tmp.model_path);
                if (ret != CVI_SUCCESS) { return ret; }

                DIR* dirp = opendir(tmp.test_images_path);
                if (dirp == NULL) {
                    perror("opendir failed");
                    return -1;
                }

                struct dirent * dp;
                double fps = 0.0;
                double fps_sum = 0.0;
                double fps_min = 1000.0;
                double fps_max = 0.0;
                int counter = 0;
                int frame_h = 0, frame_w = 0;
                
                while ((dp = readdir(dirp)) != NULL) {
                if (!strcmp(dp->d_name, "..") || !strcmp(dp->d_name, ".")) continue; // Skip ../ path
                    VIDEO_FRAME_INFO_S bg;
                    char absFilePath[512];
                    sprintf(absFilePath, "%s/%s", "coco128/", dp->d_name);
                    
                    ret = CVI_TDL_ReadImage(img_handle, absFilePath, &bg, PIXEL_FORMAT_RGB_888_PLANAR);

                    cvtdl_object_t obj_meta = {0};
                    std::chrono::steady_clock::time_point begin = std::chrono::steady_clock::now();
                    CVI_TDL_YOLOV8_Detection(tdl_handle, &bg, &obj_meta);
                    std::chrono::steady_clock::time_point end = std::chrono::steady_clock::now();
                    fps = 1 / std::chrono::duration<double>(end - begin).count();
                    fps_sum += fps;
                    fps_max = std::max(fps_max, fps);
                    fps_min = std::min(fps_min, fps);
                    frame_h = bg.stVFrame.u32Height;
                    frame_w = bg.stVFrame.u32Width;

                    printf("IMG %s, %d: %lf\n", dp->d_name, counter, fps);
                    counter++;
                    CVI_TDL_ReleaseImage(img_handle, &bg);
                }
                fps_sum = fps_sum / counter;
                printf("\n\n-------\nProcessed images: %d\nFrame size: %dx%d\nAVG FPS: %lf\nMin FPS: %lf\nMax FPS: %lf\n-------\n", counter, frame_h, frame_w, fps_sum, fps_min, fps_max);

            }
            
        }
        fclose(fp);
    }

    CVI_TDL_Destroy_ImageProcessor(img_handle);
    CVI_TDL_DestroyHandle(tdl_handle);
    
    
    return ret;
}
Объяснить с
Обучение и конвертация
Milk-V Duo 256
Этапы и общая схема процесса экспорта модели:

PyTorch model -> ONNX model -> MLIR model -> calibration -> INT8 cvimodel
PyTorch model -> ONNX model -> MLIR model -> calibration -> INT8 cvimodel
Для экспорта потребуется MLIR Toolkit. В официальной документации его рекомендуется использовать внутри Docker контейнера, но чтобы инструкцией могли воспользоваться те, у кого нет возможности использовать Docker, я подготовил Jupyter Notebook для Google Colab, который позволяет выполнить экспорт модели прямо в бразуере. В ноутбуке приводится пример экспорта модели YOLOv8n, но для YOLOv11 нужно будет просто заменить название/путь модели.

Первые две части настраивают окружение: устанавливается более старая версия Python (3.10) и tpu_mlir.

Настройка Google Colab окружения
Настройка Google Colab окружения
Далее выполняется экспорт весов YOLO в формат ONNX, при этом forward метод модели заменяется, поэтому для конвертации используется отдельный скрипт:

from ultralytics import YOLO
import types
import sys

input_size = (int(sys.argv[2]), int(sys.argv[3]))

def forward2(self, x):
  x_reg = [self.cv2[i](x[i]) for i in range(self.nl)]
  x_cls = [self.cv3[i](x[i]) for i in range(self.nl)]
  return x_reg + x_cls

model_path = sys.argv[1]
model = YOLO(model_path)
model.model.model[-1].forward = types.MethodType(forward2, model.model.model[-1])
model.export(format='onnx', opset=11, imgsz=input_size)
Объяснить с
Первым аргументом он принимает путь к весам, который можно заменить на путь к весам кастомной модели. Следующие два аргумента указывают размер входного изображения. Я тестировал модели с входными размерами 640x640 и 320x320.

Экспорт модели из PyTorch в ONNX
Экспорт модели из PyTorch в ONNX
В процессе экспорта модели из MLIR в cvimodel понадобится одна тестовая картинка (например, bus.jpg для COCO моделей). Вы можете заменить её на свою, если конвертируете кастомную YOLO модель.

Подготовка к конвертации модели в MLIR
Подготовка к конвертации модели в MLIR
Также через переменные окружения указываются размеры изображения (в виде строк), путь к датасету для калибровки (о нём позже), количество изображений для калибровки и название модели для экспорта (без расширения).

Следующие 3 ячейки конвертируют ONNX веса в MLIR, калибруют модель и экспортируют в cvimodel.

Экспорт в MLIR -> CVIMODEL
Экспорт в MLIR -> CVIMODEL
Аргументы команды первой ячейки:

model_def - путь к весам модели в ONNX

input_shapes - размер входных данных (в основном менять нужно только 2 последних числа, обозначающие ширину и высоту входного изображения)

mean и scale - описывают кодирование цвета, каждый цвет пикселя (r,g,b) кодируется в float от 0 до 1, а значение 0.0039216 в scale = 1/255 (1 байт на цвет)

Список всех параметров, которые принимает model_transform.py (взято из TPU MLIR Quick Start Guide, в нем можно подробнее почитать про процесс экспорта):

Все параметры экспорта в MLIR
Все параметры экспорта в MLIR
После выполнения model_transform ONNX модель преобразуется в формат MLIR. Затем необходимо составить матрицу калибровки, которая для каждого изображения из выборки будет рассчитывать результаты, полученные оригинальной моделью и квантизированной моделью, чтобы затем сопоставить их и минимизировать ошибку, вызванную снижением разрядности весов.

Для калибровки модели COCO используется датасет COCO2017, изображения которого из коробки есть в TPU MLIR SDK. Путь к нему задаётся через переменную среды CALIBRATION_DATASET_PATH, как указано выше. Количество изображений, используемых для калибровки, настраивается в переменной CALIBRATION_IMAGES_COUNT. Рекомендуется использовать все изображения датасета для калибровки, однако для экономии времени можно выбрать только часть из них. Также возможно имеет смысл использовать для калибровки отдельный датасет, который не использовался в процессе обучения модели.

Во время калибровки инференс моделей выполняется на процессоре, без возможности переноса на GPU (CUDA). Поэтому этот этап является самым длительным в процессе конвертации модели.

В конечном итоге последняя ячейка экспортирует квантизированную модель в файл ./result/yolov8n_cv181x_int8_sym.cvimodel (имя файла зависит от начального названия модели).

Итоговая иерархия файлов
Итоговая иерархия файлов
Именно эта модель будет запускаться на плате. Список всех параметров для последней команды (model_deploy.py):

Все параметры экспорта модели в cvimodel
Все параметры экспорта модели в cvimodel
При экспорте для SoC’а SG2002 (в MLIR используется название NPU чипа cv181x) можно использовать 2 вида квантизации: INT8 и BF16. Но при экспорте и запуске BF16 YOLO модели она не обнаруживала ни одного объекта. 

Поддержка разных рамеров весов на разных NPU чипах от CVITEK
Поддержка разных рамеров весов на разных NPU чипах от CVITEK
Инференс на плате
Текущий пример находится в Projects/Yolov8.

Простой пример инференса YOLO на изображении из файла.

Код инференса:

#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <chrono>
#include <functional>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#include "core/cvi_tdl_types_mem_internal.h"
#include "core/utils/vpss_helper.h"
#include "cvi_tdl.h"
#include "cvi_tdl_media.h"

#define MODEL_SCALE 0.0039216
#define MODEL_MEAN 0.0
#define MODEL_CLASS_CNT 80
#define MODEL_THRESH 0.8
#define MODEL_NMS_THRESH 0.8

// set preprocess and algorithm param for yolov8 detection
// if use official model, no need to change param (call this function)
CVI_S32 init_param(const cvitdl_handle_t tdl_handle)
{
    // setup preprocess
    YoloPreParam preprocess_cfg =
        CVI_TDL_Get_YOLO_Preparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION);

    for (int i = 0; i < 3; i++)
    {
        printf("asign val %d \n", i);
        preprocess_cfg.factor[i] = MODEL_SCALE;
        preprocess_cfg.mean[i] = MODEL_MEAN;
    }
    preprocess_cfg.format = PIXEL_FORMAT_RGB_888_PLANAR;

    printf("setup yolov8 param \n");
    CVI_S32 ret = CVI_TDL_Set_YOLO_Preparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION,
                                            preprocess_cfg);
    if (ret != CVI_SUCCESS)
    {
        printf("Can not set yolov8 preprocess parameters %#x\n", ret);
        return ret;
    }

    // setup yolo algorithm preprocess
    YoloAlgParam yolov8_param =
        CVI_TDL_Get_YOLO_Algparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION);
    yolov8_param.cls = MODEL_CLASS_CNT;

    printf("setup yolov8 algorithm param \n");
    ret =
        CVI_TDL_Set_YOLO_Algparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, yolov8_param);
    if (ret != CVI_SUCCESS)
    {
        printf("Can not set yolov8 algorithm parameters %#x\n", ret);
        return ret;
    }

    // set theshold
    CVI_TDL_SetModelThreshold(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, MODEL_THRESH);
    CVI_TDL_SetModelNmsThreshold(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, MODEL_NMS_THRESH);

    printf("yolov8 algorithm parameters setup success!\n");
    return ret;
}

int main(int argc, char *argv[])
{
    int vpssgrp_width = 1920;
    int vpssgrp_height = 1080;
    CVI_S32 ret = MMF_INIT_HELPER2(vpssgrp_width, vpssgrp_height, PIXEL_FORMAT_RGB_888, 1,
                                   vpssgrp_width, vpssgrp_height, PIXEL_FORMAT_RGB_888, 1);
    if (ret != CVI_TDL_SUCCESS)
    {
        printf("Init sys failed with %#x!\n", ret);
        return ret;
    }

    cvitdl_handle_t tdl_handle = NULL;
    ret = CVI_TDL_CreateHandle(&tdl_handle);
    if (ret != CVI_SUCCESS)
    {
        printf("Create tdl handle failed with %#x!\n", ret);
        return ret;
    }

    std::string strf1(argv[2]);

    // change param of yolov8_detection
    ret = init_param(tdl_handle);

    ret = CVI_TDL_OpenModel(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, argv[1]);

    if (ret != CVI_SUCCESS)
    {
        printf("open model failed with %#x!\n", ret);
        return ret;
    }
    imgprocess_t img_handle;
    CVI_TDL_Create_ImageProcessor(&img_handle);

    VIDEO_FRAME_INFO_S bg;
    ret = CVI_TDL_ReadImage(img_handle, strf1.c_str(), &bg, PIXEL_FORMAT_RGB_888_PLANAR);
    if (ret != CVI_SUCCESS)
    {
        printf("open img failed with %#x!\n", ret);
        return ret;
    }
    else
    {
        printf("image read,width:%d\n", bg.stVFrame.u32Width);
        printf("image read,hidth:%d\n", bg.stVFrame.u32Height);
    }

    cvtdl_object_t obj_meta = {0};
    std::chrono::steady_clock::time_point begin = std::chrono::steady_clock::now();
    CVI_TDL_YOLOV8_Detection(tdl_handle, &bg, &obj_meta);
    std::chrono::steady_clock::time_point end = std::chrono::steady_clock::now();
    double fps = 1 / std::chrono::duration<double>(end - begin).count();
    printf("\n\n----------\nDetection FPS: %lf\nDetected objects cnt: %d\n\nDetected objects:\n", fps, obj_meta.size);
    for (uint32_t i = 0; i < obj_meta.size; i++)
    {
        printf("x1 = %lf, y1 = %lf, x2 = %lf, y2 = %lf, cls: %d, score: %lf\n", obj_meta.info[i].bbox.x1, obj_meta.info[i].bbox.y1, obj_meta.info[i].bbox.x2, obj_meta.info[i].bbox.y2, obj_meta.info[i].classes, obj_meta.info[i].bbox.score);
    }

    CVI_TDL_ReleaseImage(img_handle, &bg);
    CVI_TDL_DestroyHandle(tdl_handle);
    CVI_TDL_Destroy_ImageProcessor(img_handle);
    return ret;
}
Объяснить с
CMakeLists.txt:

cmake_minimum_required(VERSION 3.10)
project(sample_yolov8)

set(CMAKE_C_COMPILER "$ENV{COMPILER}/riscv64-unknown-linux-musl-g++")
set(CMAKE_CXX_FLAGS "-march=rv64imafd -O3 -DNDEBUG -D_MIDDLEWARE_V2_ -DC906 -DUSE_TPU_IVE -fsigned-char -Werror=all -Wno-format-truncation -fdiagnostics-color=always -s")

include_directories(
    $ENV{SDK_PATH}/cvitek_tdl_sdk/include
    $ENV{SDK_PATH}/cvitek_tdl_sdk/include/cvi_tdl
    $ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/include
    $ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/include/linux
)

set(SOURCE_FILES main.c)
set(EXECUTABLE_OUTPUT_PATH ${CMAKE_BINARY_DIR}/bin)
file(MAKE_DIRECTORY ${EXECUTABLE_OUTPUT_PATH})

add_executable(sample_yolov8 ${SOURCE_FILES})

target_link_libraries(sample_yolov8
    -mcpu=c906fdv
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/lib
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/lib/3rd
    -lini -lsns_full -lsample -lisp -lvdec -lvenc -lawb -lae -laf -lcvi_bin -lcvi_bin_isp -lmisc -lisp_algo -lsys -lvpu
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/opencv/lib
    -lopencv_core -lopencv_imgproc -lopencv_imgcodecs
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/tpu/lib
    -lcnpy -lcvikernel -lcvimath -lcviruntime -lz -lm
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/ive/lib
    -lcvi_ive_tpu
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/lib
    -lcvi_tdl
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/lib
    -lpthread -latomic
)
Объяснить с
Функция init_param настраивает параметры модели: scale, mean, количество классов, тип модели (для YOLOv11 подходит тип модели YOLOv8). В начале есть несколько дефайнов, значения которых используются при инициализации:

MODEL_SCALE = 0.0039216 - scale цветов, такой же как при экспорте в TPU MLIR

MODEL_MEAN = 0.0 - mean цветов, такой же при экспорте в TPU MLIR

MODEL_CLASS_CNT = 80 - количество классов, которые детектирует модель (в данном случае COCO - 80 классов)

MODEL_THRESH = 0.8 - порог фильтра детекции объектов

MODEL_NMS_THRESH = 0.8 - порог NMS фильтра

Собрать пример можно локально на Linux компьютере или в Google Colab ноутбуке.

Ячейка для сборки примера Yolov8 в Google Colab ноутбуке
Ячейка для сборки примера Yolov8 в Google Colab ноутбуке
При сборке потребуется наличие TDL SDK, скачать его можно здесь, затем его необходимо распаковать:

tar xvf cvitek_tdl_sdk_1228.tar.gz -C CVI_SDK
export COMPILER_PATH="путь к кросс-компилятору"
export SDK_PATH="путь к директории CVI_SDK, в которой находится cvitek_tdl_sdk"
Объяснить с
Компиляция:

mkdir build && cd build
cmake ..
make
Объяснить с
Запуск на плате:

# установка LD_LIBRARY_PATH (если не автоматизировали в /etc/profile)
export LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch/tpu_sdk_libs:/root/libs_patch:/root/libs_patch/opencv

./sample_yolov8 yolov8n_coco_640.cvimodel bus_640.jpg
Объяснить с
В качестве аргументов запуска необходимо подавать путь к весам и путь к тестовому изображению. Его пропорции должны совпадать с пропорциями входных размеров модели (т.е. в модель 320x320 можно подать изображение 640x640, но нельзя подать 640x480). 

Пример работы:

# ./sample_yolov8 yolov8n_coco_640.cvimodel bus_640.jpg
---------------------openmodel-----------------------version: 1.4.0
yolov8n Build at 2025-01-17 12:48:09 For platform cv181x
Max SharedMem size:2457600
---------------------to do detection-----------------------
image read,width:640
image read,hidth:640


----------
Detection FPS: 18.177214
Detected objects cnt: 5

Detected objects:
x1 = 42.027672, y1 = 234.737930, x2 = 189.531281, y2 = 536.424988, cls: 0, score: 0.866496
x1 = 529.857666, y1 = 230.736252, x2 = 639.212769, y2 = 520.091125, cls: 0, score: 0.866496
x1 = 4.051300, y1 = 135.388489, x2 = 637.122925, y2 = 445.642975, cls: 5, score: 0.832456
x1 = 176.457748, y1 = 242.180679, x2 = 272.009369, y2 = 508.060699, cls: 0, score: 0.832456
x1 = 0.000000, y1 = 326.076141, x2 = 59.022076, y2 = 516.136963, cls: 0, score: 0.566403
Объяснить с
В следующем разделе будет рассмотрен пример с детекцией в реальном времени с CSI-камеры и визуализацией работы в MJPEG стриме.

Кастомная модель
Кастомная модель будет детектировать два класса: красные и синие посадочные полотна для FPV дронов:

При дневном освещении кадры получаются великолепные, хорошая камера, только автофокуса не хватает
При дневном освещении кадры получаются великолепные, хорошая камера, только автофокуса не хватает

Аналитика датасета:

Изображений в датасете достаточно мало
Изображений в датасете достаточно мало
Распределение
Распределение
Области разметки
Области разметки
В качестве базовой модели будет использоваться YOLOv11n, так как она работает немного быстрее YOLOv8n. Модель обучалась с дефолтными гиперпараметрами на 50-ти эпохах. 

Графики метрик в процессе обучения:

Метрики в процессе обучения
Метрики в процессе обучения
Матрица несоответствий при определении классов:

Все классы детектируются корректно
Все классы детектируются корректно
Текущий пример находится в Projects/YoloCamera.

Пример кода с чтением кадров с CSI-камеры и стримингом визуализации детектирования в MJPEG:

#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <chrono>
#include <functional>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#include <signal.h>
#include "core/cvi_tdl_types_mem_internal.h"
#include "core/utils/vpss_helper.h"
#include "cvi_tdl.h"
#include "cvi_tdl_media.h"

#include <opencv2/core/core.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <opencv2/imgproc/imgproc.hpp>

#include "MJPEGWriter.h"

#define MODEL_SCALE 0.0039216
#define MODEL_MEAN 0.0
#define MODEL_CLASS_CNT 2
#define MODEL_THRESH 0.2
#define MODEL_NMS_THRESH 0.2
#define BLUE_MAT cv::Scalar(255, 0, 0)
#define RED_MAT cv::Scalar(0, 0, 255)

volatile uint8_t interrupted = 0;

void interrupt_handler(int signum)
{
    printf("Signal: %d\n", signum);
    interrupted = 1;
}

// set preprocess and algorithm param for yolov8 detection
// if use official model, no need to change param (call this function)
CVI_S32 init_param(const cvitdl_handle_t tdl_handle)
{
    // setup preprocess
    YoloPreParam preprocess_cfg =
        CVI_TDL_Get_YOLO_Preparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION);

    for (int i = 0; i < 3; i++)
    {
        printf("asign val %d \n", i);
        preprocess_cfg.factor[i] = MODEL_SCALE;
        preprocess_cfg.mean[i] = MODEL_MEAN;
    }
    preprocess_cfg.format = PIXEL_FORMAT_RGB_888_PLANAR;

    printf("setup yolov8 param \n");
    CVI_S32 ret = CVI_TDL_Set_YOLO_Preparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION,
                                            preprocess_cfg);
    if (ret != CVI_SUCCESS)
    {
        printf("Can not set yolov8 preprocess parameters %#x\n", ret);
        return ret;
    }

    // setup yolo algorithm preprocess
    YoloAlgParam yolov8_param =
        CVI_TDL_Get_YOLO_Algparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION);
    yolov8_param.cls = MODEL_CLASS_CNT;

    printf("setup yolov8 algorithm param \n");
    ret =
        CVI_TDL_Set_YOLO_Algparam(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, yolov8_param);
    if (ret != CVI_SUCCESS)
    {
        printf("Can not set yolov8 algorithm parameters %#x\n", ret);
        return ret;
    }

    // set theshold
    CVI_TDL_SetModelThreshold(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, MODEL_THRESH);
    CVI_TDL_SetModelNmsThreshold(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, MODEL_NMS_THRESH);

    printf("yolov8 algorithm parameters setup success!\n");
    return ret;
}

int main(int argc, char *argv[])
{

    signal(SIGINT, interrupt_handler);
    MJPEGWriter test(7777);

    cv::VideoCapture cap;
    cv::Mat bgr;

    cap.open(0);
    // cap.set(cv::CAP_PROP_FRAME_WIDTH, 320);
    // cap.set(cv::CAP_PROP_FRAME_HEIGHT, 320);
    cap >> bgr;

    test.write(bgr);
    test.start();

    printf("Pointer for High-Level code: %p\n", cap.image_ptr);
    VIDEO_FRAME_INFO_S *frame_ptr = (VIDEO_FRAME_INFO_S *)cap.image_ptr;

    CVI_S32 ret;
    // VSSGRP already inited by VideoCapture from OpenCV Mobile, second init will do some strange and cause memory problems

    cvitdl_handle_t tdl_handle = NULL;
    ret = CVI_TDL_CreateHandle(&tdl_handle);
    if (ret != CVI_SUCCESS)
    {
        printf("Create tdl handle failed with %#x!\n", ret);
        return ret;
    }

    cap >> bgr;
    // cv::imwrite("captured.jpg", bgr);
    VIDEO_FRAME_INFO_S frame = *frame_ptr;

    // change param of yolov8_detection
    ret = init_param(tdl_handle);

    ret = CVI_TDL_OpenModel(tdl_handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, argv[1]);

    if (ret != CVI_SUCCESS)
    {
        printf("open model failed with %#x!\n", ret);
        return ret;
    }

    printf("image read,width:%d\n", frame.stVFrame.u32Width);
    printf("image read,hidth:%d\n", frame.stVFrame.u32Height);

    while (!interrupted)
    {
        cap >> bgr;
        VIDEO_FRAME_INFO_S frame = *frame_ptr;
        cvtdl_object_t obj_meta = {0};
        // std::chrono::steady_clock::time_point begin = std::chrono::steady_clock::now();
        CVI_TDL_YOLOV8_Detection(tdl_handle, &frame, &obj_meta);
        // std::chrono::steady_clock::time_point end = std::chrono::steady_clock::now();
        // double fps = 1 / std::chrono::duration<double>(end - begin).count();
        // printf("\n\n----------\nDetection FPS: %lf\nDetected objects cnt: %d\n\nDetected objects:\n", fps, obj_meta.size);
        for (uint32_t i = 0; i < obj_meta.size; i++)
        {
            // printf("x1 = %lf, y1 = %lf, x2 = %lf, y2 = %lf, cls: %d, score: %lf\n", obj_meta.info[i].bbox.x1, obj_meta.info[i].bbox.y1, obj_meta.info[i].bbox.x2, obj_meta.info[i].bbox.y2, obj_meta.info[i].classes, obj_meta.info[i].bbox.score);
            cv::Rect r = cv::Rect(obj_meta.info[i].bbox.x1, obj_meta.info[i].bbox.y1, obj_meta.info[i].bbox.x2 - obj_meta.info[i].bbox.x1, obj_meta.info[i].bbox.y2 - obj_meta.info[i].bbox.y1);

            if (obj_meta.info[i].classes == 0)
                cv::rectangle(bgr, r, BLUE_MAT, 1, 8, 0);
            else if (obj_meta.info[i].classes == 1)
                cv::rectangle(bgr, r, RED_MAT, 1, 8, 0);

            cv::putText(bgr,
                        "Mat",
                        cv::Point(obj_meta.info[i].bbox.x1, obj_meta.info[i].bbox.y1 - 5),
                        cv::FONT_HERSHEY_DUPLEX,
                        1.0,
                        (obj_meta.info[i].classes == 0) ? BLUE_MAT : RED_MAT,
                        1);
        }
        test.write(bgr);
        bgr.release();
    }

    printf("Stopping stream:\n");
    test.stop();
    cap.release();

    CVI_TDL_DestroyHandle(tdl_handle);

    return ret;
}
Объяснить с
CMakeLists.txt:

cmake_minimum_required(VERSION 3.10)
project(stream_yolov8)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_C_COMPILER "$ENV{COMPILER}/riscv64-unknown-linux-musl-g++")
SET(CMAKE_CXX_COMPILER "$ENV{COMPILER}/riscv64-unknown-linux-musl-g++")
SET(CMAKE_C_LINK_EXECUTABLE "$ENV{COMPILER}/riscv64-unknown-linux-musl-ld")

set(CMAKE_CXX_FLAGS "-march=rv64imafd -O3 -DNDEBUG -D_MIDDLEWARE_V2_ -DC906 -DUSE_TPU_IVE -fsigned-char -Werror=all -Wno-format-truncation -fdiagnostics-color=always -s")

set(OpenCV_DIR "${CMAKE_CURRENT_SOURCE_DIR}/libs/opencv-mobile-4.10.0-licheerv-nano/lib/cmake/opencv4")
find_package(OpenCV REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})


include_directories(
    $ENV{SDK_PATH}/cvitek_tdl_sdk/include
    $ENV{SDK_PATH}/cvitek_tdl_sdk/include/cvi_tdl
    $ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/include
    $ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/include/linux
    $ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/include/isp/cv181x
    $ENV{SDK_PATH}/cvitek_tdl_sdk/sample/utils
    $ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/rtsp/include/cvi_rtsp
    # ${OpenCV_INCLUDE_DIRS}
)

set(SOURCE_FILES main.c)
set(EXECUTABLE_OUTPUT_PATH ${CMAKE_BINARY_DIR}/bin)
file(MAKE_DIRECTORY ${EXECUTABLE_OUTPUT_PATH})

add_executable(stream_yolov8 MJPEGWriter.cpp ${SOURCE_FILES})

target_link_libraries(stream_yolov8
    -mcpu=c906fdv
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/lib
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/middleware/v2/lib/3rd
    -lini -lsns_full -lsample -lisp -lvdec -lvenc -lawb -lae -laf -lcvi_bin -lcvi_bin_isp -lmisc -lisp_algo -lsys -lvpu
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/opencv/lib
    -lopencv_core -lopencv_imgproc -lopencv_imgcodecs
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/tpu/lib
    -lcnpy -lcvikernel -lcvimath -lcviruntime -lz -lm
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/ive/lib
    -lcvi_ive_tpu
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/lib
    -lcvi_tdl
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/3rd/lib
    -L$ENV{SDK_PATH}/cvitek_tdl_sdk/sample/utils
    -lpthread -latomic
    ${OpenCV_LIBS}
)
Объяснить с
Важным отличием от примера инференса без OpenCV Mobile является отсутствие инициализации VPSS:

CVI_S32 ret = MMF_INIT_HELPER2(vpssgrp_width, vpssgrp_height, PIXEL_FORMAT_RGB_888, 1,
                               	vpssgrp_width, vpssgrp_height, PIXEL_FORMAT_RGB_888, 1);
Объяснить с
Эта инициализация выполняется внутри VideoCapture.open в OpenCV Mobile. Повторный вызов приводит к проблемам и некорректной работе TDL SDK.

OpenCV Mobile под капотом читает кадры с камеры с помощью методов TDL SDK, который возвращает кадры в виде структуры VIDEO_FRAME_INFO_S (изображение в такой структуре необходимо передавать на инференс). А затем конвертирует их в cv::Mat. Обратная конвертация cv::Mat в VIDEO_FRAME_INFO_S после чтения кадра выглядит неэффективно. Поэтому в OpenCV Mobile я добавил возможность получать из основного кода указатель на оригинальное прочитанное с камеры изображение в формате VIDEO_FRAME_INFO_S.

В результате стало возможным работать сразу с двумя одинаковыми кадрами: один используется для инференса (VIDEO_FRAME_INFO_S), а второй (cv::Mat) — для визуализации средствами OpenCV Mobile:

cv::VideoCapture cap;
cv::Mat bgr;
cap.open(0);
cap >> bgr;
VIDEO_FRAME_INFO_S *frame_ptr = (VIDEO_FRAME_INFO_S *)cap.image_ptr;
// …
VIDEO_FRAME_INFO_S frame = *frame_ptr;
CVI_TDL_YOLOV8_Detection(tdl_handle, &frame, &obj_meta);
Объяснить с
В итоге после запуска программы на платы на 7777 порту можно наблюдать MJPEG стрим с визуализацией детекции YOLO (в видео работает модель на изображения 320x320):

Ниже ссылка на видео в нормальном качестве
Ниже ссылка на видео в нормальном качестве
Видео без сжатия в gif

В итоге стабильная детекция происходит на расстоянии до 2-2.5 метров. Добиться детектирования на большем расстоянии можно, расширив датасет, так как в текущем датасете все полотна были на удалении до 1 метра.

LLM
Текущий пример находится в Projects/LLama.

Инференс LLM на NPU реализовать пока не удалось, но лёгкие модели достаточно быстро работают на процессоре. В качестве примера будет продемонстрирован запуск llama2 - реализация архитектуры LLama на Си. Готовые бинарники и модели можно скачать здесь.

Для компиляции нужно сначала скачать исходники llama2.c, а затем применить небольшой патч, который изменит параметры компилятора:

git clone https://github.com/karpathy/llama2.c
cd llama2.c
Объяснить с
Применение патча и компиляция:

patch -p1 -i ../compilation_fixes.patch
export COMPILER=... # Путь к директории с кросс-компилятором
make
Объяснить с
Исходник патча:

Сборка со всеми флагами для оптимизации
Сборка со всеми флагами для оптимизации
Теперь на плату надо скопировать run, а также tokenizer.bin и веса модели, в качестве примера возьмём stories15M.bin.

В итоге модель на 15 миллионов параметров работает на плате со скоростью ~8 токенов в секунду. 

Для более сложных моделей, например tinyllama, требуется портирование инференса на NPU, которым я пока не занимался, но возможно это станет темой для следующих статей.

Заключение
LicheeRV Nano — компактная, но мощная платформа, объединяющая возможности Linux, FreeRTOS и встроенного нейропроцессора (NPU), что делает её перспективным решением для встраиваемых систем и робототехники. В этой статье были рассмотрены основные возможности платы, примеры работы с периферией и запуск инференса нейросетей.

Одним из ключевых направлений развития подобных устройств является интеграция NPU в робототехнические системы. Использование аппаратного ускорения для машинного зрения и других задач ИИ позволяет значительно повысить производительность и энергоэффективность автономных решений.

В следующей части будет рассмотрен практический проект, демонстрирующий, как возможности LicheeRV Nano могут быть использованы для решения реальных задач.