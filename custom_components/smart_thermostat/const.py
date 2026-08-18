"""Константы для интеграции Smart Thermostat."""

DOMAIN = "smart_thermostat"
PLATFORMS = ["sensor", "button", "climate", "switch"]

# Сигналы для dispatcher
SIGNAL_UPDATE = "smart_thermostat_update"

# Жёсткие пределы (не конфигурируются)
MIN_OFFSET = -10.0
MAX_OFFSET = 10.0

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

# Присутствие
CONF_PRESENCE_ENTITY = "presence_entity"          # Person / binary_sensor для occupancy
CONF_ECO_ENABLE = "eco_enable"                    # Включать эко-режим при отсутствии людей

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

    # Обучение и адаптация
    CONF_ENABLE_LEARNING: True,
    CONF_LEARN_RATE_FAST: DEFAULT_LEARN_RATE_FAST,
    CONF_LEARN_RATE_SLOW: DEFAULT_LEARN_RATE_SLOW,
    CONF_MIN_OFFSET_CHANGE: DEFAULT_MIN_OFFSET_CHANGE,
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