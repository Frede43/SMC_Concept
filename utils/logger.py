"""
Logger Setup
Configuration du système de logging
"""

import sys
from loguru import logger
from pathlib import Path


def setup_logger(log_level: str = "INFO", log_dir: str = "logs"):
    """
    Configure le logger avec Loguru.
    
    Args:
        log_level: Niveau de log (DEBUG, INFO, WARNING, ERROR)
        log_dir: Dossier pour les fichiers de log
    """
    # Supprimer le handler par défaut
    logger.remove()
    
    # Format personnalisé
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # Console handler
    logger.add(
        sys.stdout,
        format=log_format,
        level=log_level,
        colorize=True
    )
    
    # File handler - Info
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    logger.add(
        log_path / "smc_bot_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="INFO",
        rotation="1 day",
        retention="7 days",
        compression="zip"
    )
    
    # File handler - Errors
    logger.add(
        log_path / "errors_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="ERROR",
        rotation="1 day",
        retention="30 days"
    )
    
    # File handler - Trades
    trade_format = (
        "{time:YYYY-MM-DD HH:mm:ss} | {message}"
    )
    logger.add(
        log_path / "trades_{time:YYYY-MM-DD}.log",
        format=trade_format,
        level="INFO",
        filter=lambda record: "TRADE" in record["message"],
        rotation="1 day",
        retention="90 days"
    )
    
    logger.info("Logger initialized")
    return logger
