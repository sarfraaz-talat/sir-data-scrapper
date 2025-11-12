"""
Database loader using SQLAlchemy for voter data storage
"""

from sqlalchemy import create_engine, Column, String, Integer, DateTime, Index, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import uuid

Base = declarative_base()


class Voter(Base):
    """SQLAlchemy model for voter records."""
    
    __tablename__ = 'voters'
    
    id = Column(String, primary_key=True, nullable=False)  # Unique ID generated at runtime
    epic_no = Column(String, nullable=True)  # EPIC can be null and is no longer unique
    name_og = Column(String, nullable=True)
    name_en = Column(String, nullable=True)
    relation_type = Column(String, nullable=True)  # e.g., "Father", "Husband", "Mother"
    relation_og = Column(String, nullable=True)
    relation_en = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    address_og = Column(String, nullable=True)
    address_en = Column(String, nullable=True)
    state = Column(String, nullable=False)
    assembly = Column(String, nullable=False)
    source_file = Column(String, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes for fast filtering
    __table_args__ = (
        Index('idx_epic_no', 'epic_no'),  # Index on EPIC for lookups (not unique)
        Index('idx_state', 'state'),
        Index('idx_assembly', 'assembly'),
        Index('idx_state_assembly', 'state', 'assembly'),
    )


class DBLoader:
    """Database loader with batch insert and upsert capabilities."""
    
    def __init__(self, db_path: str = "data/voters.db"):
        """Initialize database connection."""
        self.db_path = db_path
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Create engine (SQLite)
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,
            connect_args={'check_same_thread': False}  # Allow multi-threaded access
        )
        
        # Create tables
        Base.metadata.create_all(self.engine)
        
        # Create session factory
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()
    
    def batch_insert(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> tuple[int, int]:
        """
        Insert records in batches with UPSERT logic.
        Returns (new_count, updated_count).
        """
        session = self.get_session()
        new_count = 0
        updated_count = 0
        
        try:
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                
                for record in batch:
                    # Generate unique ID for this record
                    record_id = str(uuid.uuid4())
                    
                    # Prepare voter object
                    voter = Voter(
                        id=record_id,
                        epic_no=record.get('epic_no'),  # Can be None
                        name_og=record.get('name_og'),
                        name_en=record.get('name_en'),
                        relation_type=record.get('relation_type'),
                        relation_og=record.get('relation_og'),
                        relation_en=record.get('relation_en'),
                        age=record.get('age'),
                        gender=record.get('gender'),
                        address_og=record.get('address_og'),
                        address_en=record.get('address_en'),
                        state=record.get('state'),
                        assembly=record.get('assembly'),
                        source_file=record.get('source_file'),
                        last_updated=datetime.utcnow()
                    )
                    
                    # Always insert as new record (no more UPSERT by EPIC)
                    # Each record gets a unique ID
                    session.add(voter)
                    new_count += 1
                
                # Commit batch
                session.commit()
        
        except IntegrityError as e:
            session.rollback()
            raise Exception(f"Database integrity error: {e}")
        except Exception as e:
            session.rollback()
            raise Exception(f"Database error: {e}")
        finally:
            session.close()
        
        return new_count, updated_count
    
    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        session = self.get_session()
        try:
            total = session.query(Voter).count()
            states = session.query(Voter.state).distinct().count()
            assemblies = session.query(Voter.assembly).distinct().count()
            return {
                'total_records': total,
                'states': states,
                'assemblies': assemblies
            }
        finally:
            session.close()
    
    def close(self):
        """Close database connection."""
        self.engine.dispose()

