@echo off
REM ================================================================
REM Script de Transfert vers Oracle Cloud
REM ================================================================
echo.
echo ========================================
echo   SMC Bot - Transfert vers Oracle Cloud
echo ========================================
echo.

REM Demander les informations
set /p SSH_KEY="Chemin complet vers votre cle SSH (.key): "
set /p SERVER_IP="Adresse IP de votre serveur Oracle: "

echo.
echo Verification de la cle SSH...
if not exist "%SSH_KEY%" (
    echo ERREUR: Fichier de cle non trouve: %SSH_KEY%
    pause
    exit /b 1
)

echo.
echo ========================================
echo 1/3 - Creation de l'archive...
echo ========================================
cd /d E:\SMC

REM Creer le dossier temp
if not exist "temp" mkdir temp

REM Copier les fichiers necessaires (sans les gros dossiers)
echo Copie des fichiers...
xcopy /E /I /Y "broker" "temp\broker"
xcopy /E /I /Y "config" "temp\config"
xcopy /E /I /Y "core" "temp\core"
xcopy /E /I /Y "strategy" "temp\strategy"
xcopy /E /I /Y "utils" "temp\utils"
xcopy /E /I /Y "docs" "temp\docs"
copy /Y "main.py" "temp\"
copy /Y "requirements.txt" "temp\" 2>nul
copy /Y "*.py" "temp\"

REM Creer requirements.txt si inexistant
if not exist "temp\requirements.txt" (
    echo pandas>temp\requirements.txt
    echo numpy>>temp\requirements.txt
    echo loguru>>temp\requirements.txt
    echo pyyaml>>temp\requirements.txt
    echo requests>>temp\requirements.txt
    echo ta>>temp\requirements.txt
    echo plotly>>temp\requirements.txt
)

echo.
echo ========================================
echo 2/3 - Compression...
echo ========================================

REM Compresser avec tar (disponible sur Windows 10+)
cd temp
tar -cvzf ..\smc-bot.tar.gz *
cd ..

REM Nettoyer
rmdir /s /q temp

echo.
echo ========================================
echo 3/3 - Transfert vers Oracle Cloud...
echo ========================================
echo.
echo Connexion a %SERVER_IP%...

REM Transferer l'archive
scp -i "%SSH_KEY%" smc-bot.tar.gz ubuntu@%SERVER_IP%:~/

REM Se connecter et extraire
echo.
echo Extraction sur le serveur...
ssh -i "%SSH_KEY%" ubuntu@%SERVER_IP% "cd ~ && mkdir -p smc-bot && tar -xvzf smc-bot.tar.gz -C smc-bot && rm smc-bot.tar.gz"

REM Nettoyer localement
del smc-bot.tar.gz

echo.
echo ========================================
echo TRANSFERT TERMINE !
echo ========================================
echo.
echo Prochaines etapes:
echo 1. Connectez-vous: ssh -i "%SSH_KEY%" ubuntu@%SERVER_IP%
echo 2. Installez les dependances: cd ~/smc-bot ^&^& pip install -r requirements.txt
echo 3. Lancez le bot: python main.py --mode live
echo.
pause
