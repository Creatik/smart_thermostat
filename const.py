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

# Присутствие
CONF_PRESENCE_ENTITY = "presence_entity"          # Person / binary_sensor для occupancy

# Основные параметры управления
CONF_INTERVAL_SEC = "interval_sec"
CONF_DEADBAND = "deadband"
CONF_STEP_MAX = "step_max"
CONF_STEP_MIN = "step_min"
CONF_TRV_MIN = "trv_min"
CONF_TRV_MAX = "trv_max"
CONF_COOLDOWN_SEC = "cooldown_sec"

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

# ========== ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ ==========

DEFAULTS = {
    # Основные
    CONF_ROOM_TARGET: 22.0,

    # Датчики
    CONF_HUMIDITY_SENSOR: None,
    CONF_WEATHER_ENTITY: None,
    CONF_WEATHER_FORECAST_TYPE: "hourly",
    CONF_PRESENCE_ENTITY: [],

    # Управление
    CONF_INTERVAL_SEC: 240,
    CONF_DEADBAND: 0.5,
    CONF_STEP_MAX: 1.0,
    CONF_STEP_MIN: 0.5,
    CONF_TRV_MIN: 8.0,
    CONF_TRV_MAX: 30.0,
    CONF_COOLDOWN_SEC: 600,
    CONF_COOLDOWN_REDUCTION_FACTOR: 0.3,

    # Окна и boost
    CONF_WINDOW_SENSORS: [],
    CONF_BOOST_DURATION_SEC: 300,

    # Обучение и адаптация
    CONF_ENABLE_LEARNING: True,
    CONF_LEARN_RATE_FAST: 0.5,
    CONF_LEARN_RATE_SLOW: 0.07,
    CONF_MIN_OFFSET_CHANGE: 0.1,
    CONF_NO_LEARN_SUMMER: False,
    CONF_WINDOW_OPEN_NO_LEARN_MIN: 10,  # 10 минут

    # Stuck detection
    CONF_STUCK_ENABLE: True,
    CONF_STUCK_SECONDS: 1800,
    CONF_STUCK_MIN_DROP: 0.05,
    CONF_STUCK_STEP: 0.8,

    # Динамика и предиктив
    CONF_HEATING_ALPHA: 0.1,
    CONF_OVERSHOOT_THRESHOLD: 0.5,
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
    CONF_PREDICTIVE_FACTOR: 0.3,

    # PID
    CONF_PID_KP: 0.6,
    CONF_PID_KI: 0.05,
    CONF_PID_KD: 0.1,
}