import os
import yaml
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from core.models import Base

logger = logging.getLogger(__name__)

class DatabaseManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.engine = None
        self.Session = None
        
        # Load Config
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'secrets.yaml')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    self.db_url = config.get('database', {}).get('url')
            
            if not self.db_url:
                raise ValueError("Database URL not configured in secrets.yaml. PostgreSQL is required.")
                
            # Create Engine
            # pool_pre_ping=True: Automatically reconnect if connection drops
            connect_args = {}
            if self.db_url.startswith('sqlite'):
                connect_args['check_same_thread'] = False
                connect_args['timeout'] = 10 # Increase timeout to 10s to reduce locking errors
                
            self.engine = create_engine(self.db_url, pool_pre_ping=True, connect_args=connect_args)
            
            # Create Session Factory
            self.Session = scoped_session(sessionmaker(bind=self.engine))
            
            logger.info(f"DatabaseManager initialized with {self.db_url.split('@')[-1]}")
            
        except Exception as e:
            logger.error(f"Database Initialization Failed: {e}")
            self.engine = None

    def create_tables(self):
        """Create all tables defined in models.py"""
        if self.engine:
            Base.metadata.create_all(self.engine)
            logger.info("데이터베이스 준비 완료 (테이블 점검됨)")
            
    def get_session(self):
        """Get a new DB session"""
        if not self.Session:
            raise RuntimeError("Database not initialized")
        return self.Session()
        
    def close(self):
        if self.engine:
            self.engine.dispose()

# Global Instance
db_manager = DatabaseManager()
