import logging

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)


class ProfileManager:
    def __init__(self, profiles_dir: str = "chrome_profiles"):
        from job_studio.core import DATA

        self.profile_dir = DATA / profiles_dir
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def acquire_lock(self, base_pool: list, specific_profile: str = None):
        """
        Пытается захватить профиль. Возвращает кортеж (путь_к_профилю, объект_блокировки).
        """

        # Сначала проверяем, запрошен ли конкретный профиль
        if specific_profile:
            # Формируем пути
            profile_path = self.profile_dir / specific_profile
            lock_path = self.profile_dir / f"{specific_profile}.lock"

            # Создаем объект блокировки.
            # timeout=10 означает, что мы готовы подождать 10 секунд, если файл сейчас занят другим процессом
            lock = FileLock(lock_path, timeout=10)

            try:
                lock.acquire()
                logger.info(f"Acquired lock for specific profile: {specific_profile}")
                return str(profile_path), lock
            except Timeout:
                logger.warning(
                    f"Timeout while trying to acquire lock for specific profile: {specific_profile}"
                )
                return None, None

        # Логика для любого свободного профиля из пула
        for profile_name in base_pool:
            profile_path = self.profile_dir / profile_name
            lock_path = self.profile_dir / f"{profile_name}.lock"

            # Используем timeout=0.1. FileLock моментально попытается захватить файл,
            # и если он занят другим процессом, сразу выбросит Timeout.
            lock = FileLock(lock_path, timeout=0.1)

            try:
                lock.acquire()
                logger.info(f"Acquired lock for profile: {profile_name}")
                return str(profile_path), lock
            except Timeout:
                logger.info(
                    f"Profile {profile_name} is already in use (lock busy). Trying next one."
                )
                continue  # Попробуем следующий профиль

        logger.warning("No available profiles could be locked.")
        return None, None
