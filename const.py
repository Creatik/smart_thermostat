"""Константы для Smart Offset Thermostat."""

DOMAIN = "smart_offset_thermostat"
PLATFORMS = ["sensor", "button", "climate", "switch"]

# Сигналы
SIGNAL_UPDATE = "smart_offset_thermostat_update"

# ========== ОСНОВНЫЕ КОНФИГУРАЦИОННЫЕ КОНСТАНТЫ ==========

# Обязательные параметры
CONF_CLIMATE = "climate_entity"
CONF_ROOM_SENSOR = "room_sensor_entity"
CONF_ROOM_TARGET = "room_target"

# Основные параметры управления
CONF_INTERVAL_SEC = "interval_sec"
CONF_DEADBAND = "deadband"
CONF_STEP_MAX = "step_max"
CONF_STEP_MIN = "step_min"
CONF_TRV_MIN = "trv_min"
CONF_TRV_MAX = "trv_max"
CONF_COOLDOWN_SEC = "cooldown_sec"

# Параметры обучения
CONF_LEARN_RATE_FAST = "learn_rate_fast"
CONF_LEARN_RATE_SLOW = "learn_rate_slow"
CONF_MIN_OFFSET_CHANGE = "min_offset_change"
CONF_ENABLE_LEARNING = "enable_learning"
CONF_NO_LEARN_SUMMER = "no_learn_summer"
CONF_WINDOW_OPEN_NO_LEARN_MIN = "window_open_no_learn_min"

# Параметры окон
CONF_WINDOW_SENSOR = "window_sensor_entity"  # Устаревшее, для обратной совместимости
CONF_WINDOW_SENSORS = "window_sensor_entities"

# Параметры boost
CONF_BOOST_DURATION_SEC = "boost_duration_sec"

# Параметры stuck detection
CONF_STUCK_ENABLE = "stuck_enable"
CONF_STUCK_SECONDS = "stuck_seconds"
CONF_STUCK_MIN_DROP = "stuck_min_drop"
CONF_STUCK_STEP = "stuck_step"

# Параметры overshoot prevention
CONF_HEATING_ALPHA = "heating_alpha"
CONF_OVERSHOOT_THRESHOLD = "overshoot_threshold"
CONF_PREDICT_MINUTES = "predict_minutes"

# ========== ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ ==========

# Основные параметры управления
DEFAULT_INTERVAL_SEC = 240
DEFAULT_DEADBAND = 0.2
DEFAULT_STEP_MAX = 1.0
DEFAULT_STEP_MIN = 0.5
DEFAULT_TRV_MIN = 12.0
DEFAULT_TRV_MAX = 30.0
DEFAULT_COOLDOWN_SEC = 600

# Параметры обучения
DEFAULT_LEARN_RATE_FAST = 0.5
DEFAULT_LEARN_RATE_SLOW = 0.1
DEFAULT_MIN_OFFSET_CHANGE = 0.2
DEFAULT_ENABLE_LEARNING = True
DEFAULT_NO_LEARN_SUMMER = False
DEFAULT_WINDOW_OPEN_NO_LEARN_MIN = 600  # 10 минут

# Параметры boost
DEFAULT_BOOST_DURATION_SEC = 300

# Параметры stuck detection
DEFAULT_STUCK_ENABLE = True
DEFAULT_STUCK_SECONDS = 1800
DEFAULT_STUCK_MIN_DROP = 0.10
DEFAULT_STUCK_STEP = 0.5

# Параметры overshoot prevention
DEFAULT_HEATING_ALPHA = 0.1
DEFAULT_OVERSHOOT_THRESHOLD = 0.5
DEFAULT_PREDICT_MINUTES = 5

# ========== ВНУТРЕННИЕ КОНСТАНТЫ ==========

# Параметры stable learning
STABLE_LEARN_SECONDS = 900  # 15 минут в deadband
STABLE_LEARN_ALPHA = 0.25   # смещение offset на 25% к implied значению за стабильное окно

# Параметры offset decay
OFFSET_DECAY_RATE = 0.01    # 1% decay в день
OFFSET_DECAY_THRESHOLD = 0.1  # минимальный offset для начала decay
OFFSET_LEARN_THRESHOLD = 0.5  # порог для stable learning

# Параметры stuck bias
MAX_STUCK_BIAS = 4.0        # верхний предел для stuck_bias

# ========== СЛОВАРЬ ЗНАЧЕНИЙ ПО УМОЛЧАНИЮ ==========

DEFAULTS = {
    # Обязательные параметры
    CONF_ROOM_TARGET: 22.0,
    
    # Основные параметры управления
    CONF_INTERVAL_SEC: DEFAULT_INTERVAL_SEC,
    CONF_DEADBAND: DEFAULT_DEADBAND,
    CONF_STEP_MAX: DEFAULT_STEP_MAX,
    CONF_STEP_MIN: DEFAULT_STEP_MIN,
    CONF_TRV_MIN: DEFAULT_TRV_MIN,
    CONF_TRV_MAX: DEFAULT_TRV_MAX,
    CONF_COOLDOWN_SEC: DEFAULT_COOLDOWN_SEC,
    
    # Параметры обучения
    CONF_LEARN_RATE_FAST: DEFAULT_LEARN_RATE_FAST,
    CONF_LEARN_RATE_SLOW: DEFAULT_LEARN_RATE_SLOW,
    CONF_MIN_OFFSET_CHANGE: DEFAULT_MIN_OFFSET_CHANGE,
    CONF_ENABLE_LEARNING: DEFAULT_ENABLE_LEARNING,
    CONF_NO_LEARN_SUMMER: DEFAULT_NO_LEARN_SUMMER,
    CONF_WINDOW_OPEN_NO_LEARN_MIN: DEFAULT_WINDOW_OPEN_NO_LEARN_MIN,
    
    # Параметры окон
    CONF_WINDOW_SENSORS: [],
    
    # Параметры boost
    CONF_BOOST_DURATION_SEC: DEFAULT_BOOST_DURATION_SEC,
    
    # Параметры stuck detection
    CONF_STUCK_ENABLE: DEFAULT_STUCK_ENABLE,
    CONF_STUCK_SECONDS: DEFAULT_STUCK_SECONDS,
    CONF_STUCK_MIN_DROP: DEFAULT_STUCK_MIN_DROP,
    CONF_STUCK_STEP: DEFAULT_STUCK_STEP,
    
    # Параметры overshoot prevention
    CONF_HEATING_ALPHA: DEFAULT_HEATING_ALPHA,
    CONF_OVERSHOOT_THRESHOLD: DEFAULT_OVERSHOOT_THRESHOLD,
    CONF_PREDICT_MINUTES: DEFAULT_PREDICT_MINUTES,
}

# ========== ПРОВЕРКА КОНСИСТЕНТНОСТИ ==========

# Проверяем, что все конфигурационные константы имеют значения по умолчанию
_CONFIG_CONSTANTS = [
    CONF_CLIMATE,
    CONF_ROOM_SENSOR,
    CONF_ROOM_TARGET,
    CONF_INTERVAL_SEC,
    CONF_DEADBAND,
    CONF_STEP_MAX,
    CONF_STEP_MIN,
    CONF_TRV_MIN,
    CONF_TRV_MAX,
    CONF_COOLDOWN_SEC,
    CONF_LEARN_RATE_FAST,
    CONF_LEARN_RATE_SLOW,
    CONF_MIN_OFFSET_CHANGE,
    CONF_ENABLE_LEARNING,
    CONF_NO_LEARN_SUMMER,
    CONF_WINDOW_OPEN_NO_LEARN_MIN,
    CONF_WINDOW_SENSORS,
    CONF_BOOST_DURATION_SEC,
    CONF_STUCK_ENABLE,
    CONF_STUCK_SECONDS,
    CONF_STUCK_MIN_DROP,
    CONF_STUCK_STEP,
    CONF_HEATING_ALPHA,
    CONF_OVERSHOOT_THRESHOLD,
    CONF_PREDICT_MINUTES,
]

# Устаревшие константы (для обратной совместимости)
_DEPRECATED_CONSTANTS = [
    CONF_WINDOW_SENSOR,  # Используйте CONF_WINDOW_SENSORS
]

# Внутренние константы (не конфигурируются пользователем)
_INTERNAL_CONSTANTS = [
    "STABLE_LEARN_SECONDS",
    "STABLE_LEARN_ALPHA",
    "OFFSET_DECAY_RATE",
    "OFFSET_DECAY_THRESHOLD",
    "OFFSET_LEARN_THRESHOLD",
    "MAX_STUCK_BIAS",
]