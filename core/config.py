import os
import yaml
import logging
import copy
from typing import Dict, Any

logger = logging.getLogger(__name__)

class Config:
    def __init__(self, strategies_path: str = "config/strategies.yaml", secrets_path: str = "config/secrets.yaml"):
        self.strategies_path = strategies_path
        self.secrets_path = secrets_path
        self.config = {}
        self.system_config = {}
        self.reload()

    def reload(self):
        """Reload configuration from files"""
        self.config = self._load_yaml(self.strategies_path)

        # Load secrets and merge
        secrets = self._load_yaml(self.secrets_path)
        if secrets:
            self._merge_config(self.config, secrets)
            logger.debug(f"Loaded secrets from {self.secrets_path}")

        self.system_config = self.config.get("system", {"env_type": "paper", "market_type": "KRX"})

    def _load_yaml(self, path: str) -> Dict[str, Any]:
        try:
            if not os.path.exists(path):
                logger.warning(f"Config file not found: {path}")
                return {}
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load config from {path}: {e}")
            return {}

    def _merge_config(self, base: Dict[str, Any], update: Dict[str, Any]):
        """Recursively merge update dict into base dict"""
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._merge_config(base[k], v)
            else:
                base[k] = v

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def get_system_config(self) -> Dict[str, Any]:
        return self.system_config

    def update_system_config(self, new_config: Dict[str, Any]):
        """Update system configuration and save to appropriate files"""
        # 1. Update In-Memory Config (Deep Merge)
        self._merge_config(self.system_config, new_config)

        # Update main config wrapper
        if "system" not in self.config:
            self.config["system"] = {}
        self._merge_config(self.config["system"], new_config)

        # 2. Save to Files (Split Strategy vs Secrets)
        # Load current secrets to preserve valid token/chat_id existing there
        secrets_data = self._load_yaml(self.secrets_path)

        # Ensure 'system' -> 'telegram' structure in secrets
        if "system" not in secrets_data:
            secrets_data["system"] = {}
        if "telegram" not in secrets_data["system"]:
            secrets_data["system"]["telegram"] = {}

        # Extract telegram config from new_config/system_config to update secrets
        # We use system_config because it contains the latest merged state (including UI updates)
        current_telegram_config = self.system_config.get("telegram", {})

        # Update secrets_data with current telegram config
        secrets_data["system"]["telegram"].update(current_telegram_config)

        # Save Secrets
        self._save_yaml(self.secrets_path, secrets_data)

        # Save Strategies (Exclude Telegram)
        # Create a clean copy of config for strategies.yaml
        strategies_data = copy.deepcopy(self.config)

        # Remove telegram from system in strategies_data
        if "system" in strategies_data and "telegram" in strategies_data["system"]:
            del strategies_data["system"]["telegram"]

        self._save_yaml(self.strategies_path, strategies_data)

        logger.info(f"System config saved. Telegram config -> secrets.yaml, Others -> strategies.yaml")

    def update_strategy_config(self, new_config: Dict[str, Any]):
        """Update strategy configuration (Config only, applied on restart)"""
        # new_config is a dict of {strategy_id: {config}}
        for strategy_id, config_data in new_config.items():
            if strategy_id in self.config:
                self.config[strategy_id].update(config_data)
            else:
                logger.warning(f"Strategy config {strategy_id} not found for update")

    def _save_yaml(self, path: str, data: Dict[str, Any]):
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            logger.error(f"Failed to save config to {path}: {e}")
