"""Константы для интеграции Smart Thermostat."""

DOMAIN = "smart_thermostat"
PLATFORMS = ["sensor", "button", "climate", "switch", "time"]

# Сигналы для dispatcher
SIGNAL_UPDATE = "smart_thermostat_update"

# Жёсткие пределы (не конфигурируются)
# Сужены с ±10 до ±6: при ±10 обучение улетало в пол и не могло вернуться
MIN_OFFSET = -6.0
MAX_OFFSET = 6.0

# ========== КОНФИГУРАЦИОННЫЕ КОНСТАНТЫ ==========

# Обязательные параметры (в data)
CONF_CLIMATE = "climate_entity"
CONF_ROOM_SENSORS = "room_sensor_entities"
CONF_ROOM_TARGET = "room_target"

# Датчики окружающей среды
CONF_HUMIDITY_SENSOR = "humidity_sensor"          # Датчик влажности в помещении
CONF_WEATHER_ENTITY = "weather_entity"            # Weather entity для прогноза
CONF_WEATHER_FORECAST_TYPE = "weather_forecast_type"  # "hourly" или "daily"
CONF_OUTDOOR_SENSOR = "outdoor_sensor_entity"     # Датчик наружной температуры
CONF_WEATHER_BASE_TEMP = "weather_base_temp"      # Уличная темп., ниже которой начинается компенсация
CONF_WEATHER_MAX_COMP = "weather_max_comp"        # Макс. компенсация (°C)

# Присутствие / occupancy (предпочтительный путь вместо жёстких часов)
CONF_PRESENCE_ENTITY = "presence_entity"  # person.* / device_tracker / binary_sensor
CONF_OCCUPANCY_ACTIVITY = "occupancy_activity_entities"  # свет, чайник, motion…
CONF_OCCUPANCY_HOLD_MIN = "occupancy_hold_min"  # держать «дома» после активности
CONF_ECO_ENABLE = "eco_enable"
DEFAULT_OCCUPANCY_HOLD_MIN = 45
# Прогрев при приходе (person home / активность после отсутствия)
ARRIVAL_BOOST_SEC = 1200
# Motion/presence часто мигает (кухня) → без кулдауна arrival_warmup
# десятки раз/сутки и гонит offset к +6 (дамп 02.11, гостиная).
ARRIVAL_WARMUP_COOLDOWN_SEC = 3600
# Выученный график приходов → предпрогрев (не жёсткие часы)
CONF_LEARNED_PREHEAT_ENABLE = "learned_preheat_enable"
CONF_LEARNED_PREHEAT_LEAD_MIN = "learned_preheat_lead_min"
DEFAULT_LEARNED_PREHEAT_ENABLE = True
DEFAULT_LEARNED_PREHEAT_LEAD_MIN = 45  # позже пользователь выберет 30 / 60
LEARNED_PREHEAT_MIN_SAMPLES = 3
LEARNED_ARRIVAL_MAX_DAYS = 90
LEARNED_ARRIVAL_MAX_ENTRIES = 80

# Основные параметры управления
CONF_INTERVAL_SEC = "interval_sec"
CONF_DEADBAND = "deadband"
CONF_STEP_MAX = "step_max"
CONF_STEP_MIN = "step_min"
CONF_TRV_MIN = "trv_min"
CONF_TRV_MAX = "trv_max"
CONF_COOLDOWN_SEC = "cooldown_sec"
CONF_MIN_ON_SEC = "min_on_sec"      # мин. время «включено» перед снижением уставки (анти-дребезг)
CONF_MIN_OFF_SEC = "min_off_sec"    # мин. время «выключено» перед повышением уставки (анти-дребезг)
CONF_VALVE_EXERCISE_DAYS = "valve_exercise_days"  # период автопрокрутки клапана (0 = выкл)
CONF_VALVE_EXERCISE_SEC = "valve_exercise_sec"    # длительность автопрокрутки, сек
CONF_VALVE_SWITCH_ENTITY = "valve_switch_entity"  # переключатель клапана (напр. switch.*_state для Tuya-TRV через Z2M)

# Пресеты (настроенные целевые температуры)
CONF_PRESET_COMFORT_TEMP = "preset_comfort_temp"
CONF_PRESET_ECO_TEMP = "preset_eco_temp"
CONF_PRESET_AWAY_TEMP = "preset_away_temp"
CONF_PRESET_SLEEP_TEMP = "preset_sleep_temp"

# Параметры окон и boost
CONF_WINDOW_SENSORS = "window_sensor_entities"
CONF_BOOST_DURATION_SEC = "boost_duration_sec"

# Параметры обучения и адаптации
CONF_ENABLE_LEARNING = "enable_learning"
CONF_LEARN_RATE_FAST = "learn_rate_fast"
CONF_LEARN_RATE_SLOW = "learn_rate_slow"
CONF_MIN_OFFSET_CHANGE = "min_offset_change"
CONF_MAX_OFFSET_STEP = "max_offset_step"          # макс. изменение offset за один тик (анти-взлёт)
CONF_NO_LEARN_SUMMER = "no_learn_summer"
CONF_WINDOW_OPEN_NO_LEARN_MIN = "window_open_no_learn_min"  # в минутах
CONF_COOLDOWN_REDUCTION_FACTOR = "cooldown_reduction_factor"

# Параметры stuck detection
CONF_STUCK_ENABLE = "stuck_enable"
CONF_STUCK_SECONDS = "stuck_seconds"
CONF_STUCK_MIN_DROP = "stuck_min_drop"
CONF_STUCK_STEP = "stuck_step"

# Параметры динамики и предиктива
CONF_HEATING_ALPHA = "heating_alpha"
CONF_OVERSHOOT_THRESHOLD = "overshoot_threshold"
CONF_PREDICT_MINUTES = "predict_minutes"
CONF_TTT_ALPHA = "ttt_alpha"
CONF_TTT_SOFT_MIN = "ttt_soft_min"

# Параметры stable learning и decay
CONF_STABLE_LEARN_SECONDS = "stable_learn_seconds"
CONF_STABLE_LEARN_ALPHA = "stable_learn_alpha"
CONF_OFFSET_DECAY_RATE = "offset_decay_rate"
CONF_OFFSET_DECAY_THRESHOLD = "offset_decay_threshold"
CONF_OFFSET_LEARN_THRESHOLD = "offset_learn_threshold"
CONF_MAX_STUCK_BIAS = "max_stuck_bias"

# Умные фичи
CONF_ECO_OFFSET = "eco_offset"
CONF_PREDICTIVE_FACTOR = "predictive_factor"

# PID коэффициенты
CONF_PID_KP = "pid_kp"
CONF_PID_KI = "pid_ki"
CONF_PID_KD = "pid_kd"

# Режим HVAC (если используется в опциях)
CONF_HVAC_MODE = "hvac_mode"

# UI options flow: показать экспертные поля (не влияет на контроллер)
CONF_SHOW_ADVANCED = "show_advanced"

# Опциональный предпрогрев к «готово к HH:MM» (для тех, у кого расписание
# эко↔комфорт). По умолчанию ВЫКЛ — у разных пользователей разные слоты;
# пример семейного дня: plans/family-schedule.md (не DEFAULTS).
CONF_WORKDAY_SENSOR = "workday_sensor"
CONF_PREHEAT_MORNING_READY = "preheat_morning_ready"  # "" = выкл
CONF_PREHEAT_MORNING_READY_WEEKEND = "preheat_morning_ready_weekend"
CONF_PREHEAT_EVENING_READY = "preheat_evening_ready"
CONF_PREHEAT_LEAD_MIN = "preheat_lead_min"
# Ночь без датчиков окон: не учить offset (опционально, default off)
CONF_NIGHT_OPEN_WINDOWS = "night_open_windows"
CONF_NIGHT_NO_LEARN_START = "night_no_learn_start"
CONF_NIGHT_NO_LEARN_END = "night_no_learn_end"

DEFAULT_PREHEAT_MORNING_READY = ""
DEFAULT_PREHEAT_MORNING_READY_WEEKEND = ""
DEFAULT_PREHEAT_EVENING_READY = ""
DEFAULT_PREHEAT_LEAD_MIN = 45
DEFAULT_NIGHT_OPEN_WINDOWS = False
DEFAULT_NIGHT_NO_LEARN_START = "23:00"
DEFAULT_NIGHT_NO_LEARN_END = "05:00"

# Профиль управления (простая форма → бандл DEFAULTS; advanced knobs остаются)
CONF_CONTROL_PROFILE = "control_profile"
PROFILE_ECO = "eco"
PROFILE_COMFORT = "comfort"
PROFILE_FAST = "fast_heat"
PROFILE_CUSTOM = "custom"
CONTROL_PROFILE_OPTIONS = [
    PROFILE_ECO,
    PROFILE_COMFORT,
    PROFILE_FAST,
    PROFILE_CUSTOM,
]

# «Живые» опции: меняются часто (UI/автоматизации). Их изменение НЕ требует
# перезагрузки записи — иначе все сущности мигают «unavailable» в логбуке
# при каждой смене целевой температуры или режима (см. async_update_options)
RUNTIME_OPTION_KEYS = {CONF_ROOM_TARGET, CONF_HVAC_MODE}

# ========== ПРЕСЕТЫ ==========
# Ключи активного пресета (внутренние значения для preset_mode)
PRESET_NONE = "none"
PRESET_COMFORT = "comfort"
PRESET_ECO = "eco"
PRESET_AWAY = "away"
PRESET_SLEEP = "sleep"
PRESET_MODES = [PRESET_NONE, PRESET_COMFORT, PRESET_ECO, PRESET_AWAY, PRESET_SLEEP]

# Маппинг активного пресета -> ключ опции температуры
PRESET_TEMP_OPTION = {
    PRESET_COMFORT: CONF_PRESET_COMFORT_TEMP,
    PRESET_ECO: CONF_PRESET_ECO_TEMP,
    PRESET_AWAY: CONF_PRESET_AWAY_TEMP,
    PRESET_SLEEP: CONF_PRESET_SLEEP_TEMP,
}

# ========== DEFAULT_* КОНСТАНТЫ (фолбэки) ==========
DEFAULT_INTERVAL_SEC = 240
DEFAULT_DEADBAND = 0.5
DEFAULT_STEP_MAX = 1.0
DEFAULT_STEP_MIN = 0.5
DEFAULT_TRV_MIN = 8.0
DEFAULT_TRV_MAX = 30.0
DEFAULT_COOLDOWN_SEC = 600
DEFAULT_MIN_ON_SEC = 120
DEFAULT_MIN_OFF_SEC = 120
DEFAULT_VALVE_EXERCISE_DAYS = 7
DEFAULT_VALVE_EXERCISE_SEC = 120
DEFAULT_BOOST_DURATION_SEC = 300
DEFAULT_LEARN_RATE_FAST = 0.5
DEFAULT_LEARN_RATE_SLOW = 0.07
DEFAULT_MIN_OFFSET_CHANGE = 0.1
DEFAULT_MAX_OFFSET_STEP = 0.3
DEFAULT_WINDOW_OPEN_NO_LEARN_SEC = 10  # в минутах
DEFAULT_HEATING_ALPHA = 0.1
DEFAULT_OVERSHOOT_THRESHOLD = 0.5
DEFAULT_STUCK_ENABLE = True
DEFAULT_STUCK_SECONDS = 1800
DEFAULT_STUCK_MIN_DROP = 0.05
DEFAULT_STUCK_STEP = 0.8
DEFAULT_ECO_ENABLE = True
DEFAULT_PREDICTIVE_FACTOR = 0.3
DEFAULT_WEATHER_BASE_TEMP = 5.0
DEFAULT_WEATHER_MAX_COMP = 5.0
DEFAULT_PID_KP = 0.6
DEFAULT_PID_KI = 0.05
DEFAULT_PID_KD = 0.1
DEFAULT_PRESET_COMFORT_TEMP = 22.0
DEFAULT_PRESET_ECO_TEMP = 19.0
DEFAULT_PRESET_AWAY_TEMP = 16.0
DEFAULT_PRESET_SLEEP_TEMP = 18.0

# ========== ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ ==========

DEFAULTS = {
    # Основные
    CONF_ROOM_TARGET: 22.0,

    # Датчики
    CONF_HUMIDITY_SENSOR: None,
    CONF_WEATHER_ENTITY: None,
    CONF_WEATHER_FORECAST_TYPE: "hourly",
    CONF_OUTDOOR_SENSOR: None,
    CONF_WEATHER_BASE_TEMP: DEFAULT_WEATHER_BASE_TEMP,
    CONF_WEATHER_MAX_COMP: DEFAULT_WEATHER_MAX_COMP,
    CONF_PRESENCE_ENTITY: [],
    CONF_OCCUPANCY_ACTIVITY: [],
    CONF_OCCUPANCY_HOLD_MIN: DEFAULT_OCCUPANCY_HOLD_MIN,
    CONF_LEARNED_PREHEAT_ENABLE: DEFAULT_LEARNED_PREHEAT_ENABLE,
    CONF_LEARNED_PREHEAT_LEAD_MIN: DEFAULT_LEARNED_PREHEAT_LEAD_MIN,
    CONF_ECO_ENABLE: DEFAULT_ECO_ENABLE,

    # Управление
    CONF_INTERVAL_SEC: DEFAULT_INTERVAL_SEC,
    CONF_DEADBAND: DEFAULT_DEADBAND,
    CONF_MIN_ON_SEC: DEFAULT_MIN_ON_SEC,
    CONF_MIN_OFF_SEC: DEFAULT_MIN_OFF_SEC,
    CONF_VALVE_EXERCISE_DAYS: DEFAULT_VALVE_EXERCISE_DAYS,
    CONF_VALVE_EXERCISE_SEC: DEFAULT_VALVE_EXERCISE_SEC,
    CONF_STEP_MAX: DEFAULT_STEP_MAX,
    CONF_STEP_MIN: DEFAULT_STEP_MIN,
    CONF_TRV_MIN: DEFAULT_TRV_MIN,
    CONF_TRV_MAX: DEFAULT_TRV_MAX,
    CONF_COOLDOWN_SEC: DEFAULT_COOLDOWN_SEC,
    CONF_COOLDOWN_REDUCTION_FACTOR: 0.3,

    # Окна и boost
    CONF_WINDOW_SENSORS: [],
    CONF_BOOST_DURATION_SEC: DEFAULT_BOOST_DURATION_SEC,
    CONF_VALVE_SWITCH_ENTITY: None,
    CONF_SHOW_ADVANCED: False,
    CONF_CONTROL_PROFILE: PROFILE_COMFORT,

    # Семейный день
    CONF_WORKDAY_SENSOR: None,
    CONF_PREHEAT_MORNING_READY: DEFAULT_PREHEAT_MORNING_READY,
    CONF_PREHEAT_MORNING_READY_WEEKEND: DEFAULT_PREHEAT_MORNING_READY_WEEKEND,
    CONF_PREHEAT_EVENING_READY: DEFAULT_PREHEAT_EVENING_READY,
    CONF_PREHEAT_LEAD_MIN: DEFAULT_PREHEAT_LEAD_MIN,
    CONF_NIGHT_OPEN_WINDOWS: DEFAULT_NIGHT_OPEN_WINDOWS,
    CONF_NIGHT_NO_LEARN_START: DEFAULT_NIGHT_NO_LEARN_START,
    CONF_NIGHT_NO_LEARN_END: DEFAULT_NIGHT_NO_LEARN_END,

    # Обучение и адаптация
    CONF_ENABLE_LEARNING: True,
    CONF_LEARN_RATE_FAST: DEFAULT_LEARN_RATE_FAST,
    CONF_LEARN_RATE_SLOW: DEFAULT_LEARN_RATE_SLOW,
    CONF_MIN_OFFSET_CHANGE: DEFAULT_MIN_OFFSET_CHANGE,
    CONF_MAX_OFFSET_STEP: DEFAULT_MAX_OFFSET_STEP,
    CONF_NO_LEARN_SUMMER: False,
    CONF_WINDOW_OPEN_NO_LEARN_MIN: DEFAULT_WINDOW_OPEN_NO_LEARN_SEC,  # в минутах

    # Stuck detection
    CONF_STUCK_ENABLE: DEFAULT_STUCK_ENABLE,
    CONF_STUCK_SECONDS: DEFAULT_STUCK_SECONDS,
    CONF_STUCK_MIN_DROP: DEFAULT_STUCK_MIN_DROP,
    CONF_STUCK_STEP: DEFAULT_STUCK_STEP,

    # Динамика и предиктив
    CONF_HEATING_ALPHA: DEFAULT_HEATING_ALPHA,
    CONF_OVERSHOOT_THRESHOLD: DEFAULT_OVERSHOOT_THRESHOLD,
    CONF_PREDICT_MINUTES: 10,
    CONF_TTT_ALPHA: 0.2,
    CONF_TTT_SOFT_MIN: 5.0,

    # Stable learning и decay
    CONF_STABLE_LEARN_SECONDS: 900,
    CONF_STABLE_LEARN_ALPHA: 0.25,
    CONF_OFFSET_DECAY_RATE: 0.05,
    CONF_OFFSET_DECAY_THRESHOLD: 0.05,
    CONF_OFFSET_LEARN_THRESHOLD: 0.5,
    CONF_MAX_STUCK_BIAS: 8.0,

    # Умные фичи
    CONF_ECO_OFFSET: -3.0,
    CONF_PREDICTIVE_FACTOR: DEFAULT_PREDICTIVE_FACTOR,

    # Пресеты
    CONF_PRESET_COMFORT_TEMP: DEFAULT_PRESET_COMFORT_TEMP,
    CONF_PRESET_ECO_TEMP: DEFAULT_PRESET_ECO_TEMP,
    CONF_PRESET_AWAY_TEMP: DEFAULT_PRESET_AWAY_TEMP,
    CONF_PRESET_SLEEP_TEMP: DEFAULT_PRESET_SLEEP_TEMP,

    # PID
    CONF_PID_KP: DEFAULT_PID_KP,
    CONF_PID_KI: DEFAULT_PID_KI,
    CONF_PID_KD: DEFAULT_PID_KD,
}

# ========== ПРОФИЛИ УПРАВЛЕНИЯ ==========
# Один селектор на простой форме → пакет knobs. При смене профиля бандл
# записывается в options; expert-шаг потом может переопределить отдельные ключи
# (тогда имеет смысл поставить PROFILE_CUSTOM, чтобы не затереть при следующем save).

CONTROL_PROFILES: dict[str, dict] = {
    PROFILE_ECO: {
        CONF_DEADBAND: 0.6,
        CONF_BOOST_DURATION_SEC: 180,
        CONF_LEARN_RATE_FAST: 0.35,
        CONF_LEARN_RATE_SLOW: 0.05,
        CONF_PREDICT_MINUTES: 8,
        CONF_OVERSHOOT_THRESHOLD: 0.4,
        CONF_COOLDOWN_SEC: 720,
        CONF_STEP_MAX: 0.8,
        CONF_PREDICTIVE_FACTOR: 0.2,
    },
    PROFILE_COMFORT: {
        CONF_DEADBAND: DEFAULT_DEADBAND,
        CONF_BOOST_DURATION_SEC: DEFAULT_BOOST_DURATION_SEC,
        CONF_LEARN_RATE_FAST: DEFAULT_LEARN_RATE_FAST,
        CONF_LEARN_RATE_SLOW: DEFAULT_LEARN_RATE_SLOW,
        CONF_PREDICT_MINUTES: 10,
        CONF_OVERSHOOT_THRESHOLD: DEFAULT_OVERSHOOT_THRESHOLD,
        CONF_COOLDOWN_SEC: DEFAULT_COOLDOWN_SEC,
        CONF_STEP_MAX: DEFAULT_STEP_MAX,
        CONF_PREDICTIVE_FACTOR: DEFAULT_PREDICTIVE_FACTOR,
    },
    PROFILE_FAST: {
        CONF_DEADBAND: 0.4,
        CONF_BOOST_DURATION_SEC: 600,
        CONF_LEARN_RATE_FAST: 0.7,
        CONF_LEARN_RATE_SLOW: 0.1,
        CONF_PREDICT_MINUTES: 15,
        CONF_OVERSHOOT_THRESHOLD: 0.7,
        CONF_COOLDOWN_SEC: 420,
        CONF_STEP_MAX: 1.5,
        CONF_PREDICTIVE_FACTOR: 0.45,
    },
}

# ========== ВНУТРЕННИЕ КОНСТАНТЫ ОБУЧЕНИЯ (не пользовательские опции) ==========
# Вынесены из магических чисел controller.py (правила проекта, раздел 7).
# Это жёсткие пределы-гварды (как MIN_OFFSET/MAX_OFFSET), а не настройки.

# Насыщение offset: порог, при котором смещение считается «ушедшим глубоко
# в предел». Используется и агрессивным распадом в мёртвой зоне, и быстрым
# обучением при встречной ошибке (выход из насыщения — иначе offset замирал
# у ±6 на часы, а уставка TRV оставалась ниже комнатной при закрытом клапане).
OFFSET_SATURATED_TRIGGER = 3.0
# Доля смещения, снимаемая за тик при агрессивном распаде
OFFSET_DECAY_AGG_FACTOR = 0.08
# Дребезг contact (спальня 05.11: on/off каждую секунду).
# Открылось — подтверждаем быстро, чтобы не греть улицу.
# Закрылось — ждём дольше, иначе щелчок сразу снова открывает клапан.
WINDOW_OPEN_DEBOUNCE_SEC = 8
WINDOW_CLOSE_DEBOUNCE_SEC = 45
# Мягкая подрезка в deadband при 2 < |offset| ≤ SATURATED (раньше был
# мёртвый код в active_control — hold перехватывал тик раньше).
OFFSET_TRIM_SOFT_TRIGGER = 2.0
# Потолок внутри-мёртвозонной коррекции избыточного смещения (°C/тик)
OFFSET_TRIM_MAX = 0.5

# Auto-tune learn_rate_slow: снижение при перегревах и восстановление.
# Раньше снижение было однонаправленной трещоткой (пол 0.01, возврата нет) —
# overshoot_count уходил за 2500 и медленное обучение умирало навсегда.
LEARN_RATE_FLOOR = 0.01            # нижний пол снижения rate
LEARN_RATE_AUTOTUNE_MULT = 0.9     # шаг снижения (каждые 4 тика перегрева)
LEARN_RATE_RECOVERY_SEC = 1800     # время без перегрева до шага восстановления
LEARN_RATE_RECOVERY_MULT = 1.5     # шаг восстановления (до настроенной базы)

# Мягкая посадка к уставке (гашение PID при нагреве у границы deadband).
# Физика радиатора: батарея остывает медленно → лёгкий «перелёт» цели
# терпим (остаточное тепло ещё идёт). Недогрев хуже перегрева: холодный
# чугун/вода долго разгоняются. Поэтому посадка гасит PID, но не до нуля,
# а при недогреве уставка TRV не должна падать ниже room+margin.
# (см. plans/precision-improvements.md P0-1).
SOFT_LANDING_FLOOR = 0.3           # доля PID у края deadband (было 0.2 — голодало)
SOFT_LANDING_SPAN_MULT = 2.0       # ширина полосы = max(SPAN_MIN, mult×deadband)
SOFT_LANDING_SPAN_MIN = 1.0        # нижний пол ширины полосы, °C
# Пока комната ниже цели (e > deadband): TRV ≥ room + margin, иначе
# физический клапан закрыт при «нужно греть» (гостиная: TRV<room 96%).
UNDERHEAT_TRV_MARGIN = 0.8
# Симметрия при перелёте: пока комната выше цели, TRV ≤ room − margin.
# Иначе hold/active держат target+offset (спальня: room 23.6 / TRV 25 /
# idle) — локальная на клапане остывает, уставка снова > local → клапан
# подоткрывается и батарея не остывает. Offset не трогаем, только уставку.
OVERSHOOT_TRV_MARGIN = 0.5
# Ранняя посадка на подходе к цели (пока e > 0): если батарея уже
# горячая (local ≥ room+HEAT_FLOW), не держать target+offset далеко
# выше room — иначе остаточное тепло даёт перелёт (спальня 04.11:
# room≈23 / TRV 26 / local 24+ → пик 24.3). Полоса = soft-landing.
# Потолок = room+UNDERHEAT_TRV_MARGIN: инвариант недогрева сохраняем.
APPROACH_BAND_MULT = SOFT_LANDING_SPAN_MULT
APPROACH_BAND_MIN = SOFT_LANDING_SPAN_MIN
# Предиктивная посадка: local ещё не «горячий», но сам РАСТЁТ (тепло пошло
# в батарею, датчик отстаёт) и комната по rate/TTT долетит до цели быстрее,
# чем батарея отдаст тепло. Рост только комнаты при холодном или отсутствующем
# local — не запас чугуна (солнце на датчике). Тот же потолок
# room+UNDERHEAT_TRV_MARGIN и тот же коридор ошибки.
# 12 мин, не 20: ETA считается по темпу ПОЛНОГО хода, а после среза комната
# едет на остаточном тепле чугуна/воды (~20…40 мин остывание). При ETA 20 мин
# инерция не добивает остаток → недогрев; при ETA ≤ 12 мин добивает. Прогон
# факта: 13:49 (e=0.96, ETA≈19) — не режем, 14:31 (e=0.51, ETA≈1) — режем.
APPROACH_PREDICT_MAX_MIN = 12.0     # мин до входа в deadband — уже садимся
APPROACH_RATE_MIN = 0.01            # °C/мин: ниже rate не считается «растём»
# «Комната реально растёт» — evidence для предиктивной посадки и approach_trim.
# Порог в °C/мин, не в °C за тик: при интервале 4 мин реальный рост спальни
# 0.04 °C/тик (0.01 °C/мин), а шаг квантования датчика 0.01 °C даёт 0.0025.
APPROACH_RISE_RATE_MIN = 0.005      # °C/мин (0.3 °C/ч) — уже не шум
APPROACH_RISE_DT_MIN = 1.0          # мин: короче интервал — шум квантования
# heating_rate °C/мин: отсечка шума датчика и нереальных скачков
# (0.5°C за 4 мин тика = 0.125; радиаторы обычно 0.01…0.08)
HEATING_RATE_MIN = 0.002           # ~500 мин/°C — ниже не учим
HEATING_RATE_MAX = 0.25            # 4 мин/°C — выше = выброс сенсора
# Детская 08.11: эпизод 0 мин и подъём, зажатый в 0.1°, дали mpd=2
# и вытеснили живые ~40 мин/°. Чугун так не греет — такую выборку не пишем.
TTT_MPD_MIN = 8.0                  # мин/°C: быстрее — выброс, не память
TTT_MIN_RISE = 0.3                 # °C реального подъёма комнаты за эпизод
HEATING_RATE_DT_MIN = 0.25         # мин. интервал выборки, мин
HEATING_RATE_DT_MAX = 30.0
HEATING_RATE_DTEMP_MIN = 0.01      # мин. |ΔT|, °C

# Длительность авто-boost в окне предпрогрева (сек); lead обычно длиннее —
# boost держит TRV=max, дальше active_control с полом TRV догоняет.
PREHEAT_BOOST_SEC = 1200

# Скачок цели по расписанию (эко 18 ↔ комфорт 23).
# Факт из log_server (25.10–01.11): в 05:00 цель → 23 при offset ≈ −6 →
# TRV ≈ 18 при комнате ≈ 21 → клапан закрыт; offset догоняет ~час,
# а комфортное окно утром часто всего 05–07. К пробуждению батареи холодные.
TARGET_STEP_THRESHOLD = 2.0          # |Δцели|, °C — порог «скачок расписания»
TARGET_STEP_BOOST_SEC = 1800         # авто-boost (TRV=max) при скачке вверх, сек
TARGET_STEP_VALVE_MARGIN = 1.5       # сразу поднять offset так, чтобы TRV ≥ room+margin
# Скачок смотрим по сырой цели (t_target / room_target / пресет), НЕ по
# t_effective: эко occupancy и погода дают ложные 20.3→23.3, спам boost
# и сброс learn_freeze (дамп 02.11).
# После скачка вниз (комфорт→эко) комната «перегрета» относительно эко-цели —
# обучение без заморозки за ночь прижимает offset к −6 и убивает утро.
# Снимается только при реальном скачке расписания вверх; потолок — сутки.
LEARN_FREEZE_AFTER_TARGET_DROP_SEC = 86400

# Холодный старт (room 18 / цель 23): рывок TRV=max, контроль по комнате,
# локальная температура клапана — датчик «тепло пошло».
COLD_START_ERROR = 2.0             # e ≥ 2°C → рывок
COLD_START_BOOST_SEC = 1800        # потолок рывка, сек
COLD_START_HANDOFF_ERROR = 1.0     # e < 1°C + local горячий → отдать комнате
HEAT_FLOW_LOCAL_MARGIN = 1.5       # local ≥ room+1.5 → батарея реально греет
COLD_START_RETRY_SEC = 1800        # не дёргать рывок снова слишком часто

# Датчик головы TRV. −0.01 (гостиная 07.11) и ровно 23.5 сутками при
# уставке 18→30 (спальня 07.11) — не температура радиатора.
LOCAL_TEMP_MIN = 5.0
LOCAL_TEMP_MAX = 45.0
LOCAL_STUCK_SEC = 7200             # плоская полка, сек
LOCAL_STUCK_EPSILON = 0.2          # шаг квантования, который ещё «не сдвинулся»
LOCAL_STUCK_SET_SPAN = 4.0         # размах уставки за полку, °C — иначе это удержание
LOCAL_STUCK_COMMAND_GAP = 4.0      # уставка всё время намного выше застывшего local
LOCAL_STUCK_COMMAND_SEC = 1800     # столько уже командовали «грей», а local нем

# Погодная надбавка на клапане, уже открытом до упора, только раздувает
# ошибку (цель 25 при комнате 22 и TRV 30). Снимаем, пока уставка не
# отойдёт от максимума: иначе −1.5° роняет set и надбавка включается снова.
WEATHER_SUPPRESS_RELEASE = 3.0
# 29 при максимуме 30 — клапан уже открыт. Уже этого хватает, чтобы не
# дёргать рывок и stuck.
TRV_SATURATED_MARGIN = 1.0

# Гвард «клапан без власти» (valve authority) для обучения offset.
# TRV открывается пропорционально (уставка − local): при уставке выше
# local+margin клапан уже полностью открыт — учить offset ВВЕРХ некуда,
# он улетает к +6 и позже выстреливает перегревом (детская 02.11:
# 1.8→+6 за час при мёртвой комнате 22.3 — котёл/циркуляция не тянули).
# Симметрично: уставка ниже local−margin — клапан уже закрыт, эко-«перегрев»
# иначе хоронит offset к −6 и убивает утренний прогрев.
VALVE_TRAVEL_MARGIN = 2.0          # |уставка − local|, °C — полный ход клапана

# Диагностика «источник не даёт тепло» (heat_delivery, карта улучшений P0).
# Недогрев + клапан полностью открыт столько секунд + local ниже room+margin
# → вода не греет: котёл/циркуляция не тянут (детская 02.11 18:39–19:31).
HEAT_SOURCE_ABSENT_AFTER_SEC = 600    # клапан открыт ≥10 мин без тепла → absent
HEAT_SOURCE_GRACE_AFTER_STEP_SEC = 900  # ~15 мин после step-up — unknown (разгон)
HEAT_SOURCE_LOCAL_RISE_MIN = 0.3      # рост local между наблюдениями → не absent
HEAT_SOURCE_WARN_INTERVAL_SEC = 3600  # warning не чаще раза в час