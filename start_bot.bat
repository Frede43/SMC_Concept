@echo off
setlocal enabledelayedexpansion
echo ===============================================
echo   Ultimate SMC Trading Bot - Quick Start
echo ===============================================
echo.

:: Vérifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python n'est pas installe ou pas dans le PATH
    pause
    exit /b 1
)

:: Installer les dépendances
echo [1/3] Installation des dependances...
pip install -r requirements.txt -q

:: Vérifier MT5
echo [2/3] Verification de MetaTrader 5...
python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] MetaTrader5 non installe. Installation...
    pip install MetaTrader5
)

:: Choix du mode
echo [3/3] Choix du mode d'execution:
echo 1. Mode SIGNAL (Demo/Visualisation)
echo 2. Mode TRADING (Execution Reelle/Demo MT5)
echo.
set /p choice="Votre choix (1 ou 2) [Defaut=2]: "

if "%choice%"=="1" (
    echo Lancement en mode DEMO (Signaux uniquement)...
    python main.py --mode demo
) else (
    echo Lancement en mode LIVE (Prise de trades automatique)...
    python main.py --mode live
)

pause
