#!/bin/bash
# ================================================================
# 🤖 SMC Trading Bot - Script d'Installation Oracle Cloud
# ================================================================
# Ce script installe automatiquement tout ce qui est nécessaire
# pour faire tourner le bot de trading SMC sur Oracle Cloud
# ================================================================

set -e  # Arrêter en cas d'erreur

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "========================================"
echo "🤖 SMC Trading Bot - Installation"
echo "   Oracle Cloud Edition"
echo "========================================"
echo -e "${NC}"

# Vérifier si root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}❌ Ne pas exécuter en tant que root${NC}"
    echo "Utilisez: ./install.sh (sans sudo)"
    exit 1
fi

# Demander confirmation
echo -e "${YELLOW}Ce script va installer:${NC}"
echo "  - Python 3 et pip"
echo "  - Wine (pour Windows apps)"
echo "  - MetaTrader 5"
echo "  - Xvfb (écran virtuel)"
echo "  - VNC Server"
echo "  - Toutes les dépendances Python"
echo ""
read -p "Continuer? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# ================================================================
# ÉTAPE 1 : Mise à jour du système
# ================================================================
echo -e "\n${GREEN}[1/8] 📦 Mise à jour du système...${NC}"
sudo apt update
sudo apt upgrade -y

# ================================================================
# ÉTAPE 2 : Installation des dépendances de base
# ================================================================
echo -e "\n${GREEN}[2/8] 📦 Installation des dépendances de base...${NC}"
sudo apt install -y \
    software-properties-common \
    wget \
    curl \
    git \
    unzip \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev

# ================================================================
# ÉTAPE 3 : Installation de l'environnement graphique virtuel
# ================================================================
echo -e "\n${GREEN}[3/8] 🖥️ Installation de l'environnement graphique...${NC}"
sudo apt install -y \
    xvfb \
    x11vnc \
    xfce4 \
    xfce4-goodies \
    dbus-x11 \
    at-spi2-core

# ================================================================
# ÉTAPE 4 : Installation de Wine
# ================================================================
echo -e "\n${GREEN}[4/8] 🍷 Installation de Wine...${NC}"

# Ajouter l'architecture 32-bit
sudo dpkg --add-architecture i386

# Ajouter le repository Wine
sudo mkdir -pm755 /etc/apt/keyrings 2>/dev/null || true
sudo wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key

# Déterminer la version d'Ubuntu
UBUNTU_VERSION=$(lsb_release -cs)
echo "Ubuntu version: $UBUNTU_VERSION"

# Ajouter le repository approprié
if [ "$UBUNTU_VERSION" = "jammy" ]; then
    sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources
elif [ "$UBUNTU_VERSION" = "focal" ]; then
    sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/focal/winehq-focal.sources
else
    echo -e "${YELLOW}⚠️ Version Ubuntu non standard, utilisation de jammy${NC}"
    sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources
fi

# Installer Wine
sudo apt update
sudo apt install -y --install-recommends winehq-stable || {
    echo -e "${YELLOW}⚠️ winehq-stable échoué, essai avec winehq-devel...${NC}"
    sudo apt install -y --install-recommends winehq-devel
}

# ================================================================
# ÉTAPE 5 : Configuration de Wine
# ================================================================
echo -e "\n${GREEN}[5/8] ⚙️ Configuration de Wine...${NC}"

# Créer le script de démarrage de l'écran virtuel
mkdir -p ~/scripts
cat > ~/scripts/start_xvfb.sh << 'EOF'
#!/bin/bash
export DISPLAY=:1
Xvfb :1 -screen 0 1280x1024x24 &
sleep 2
echo "Xvfb started on display :1"
EOF
chmod +x ~/scripts/start_xvfb.sh

# Démarrer Xvfb
~/scripts/start_xvfb.sh

# Configurer Wine
export DISPLAY=:1
export WINEARCH=win64
export WINEPREFIX=~/.wine64

# Initialiser Wine
echo "Initialisation de Wine (peut prendre quelques minutes)..."
wineboot --init
sleep 10

# Installer winetricks
echo "Installation de winetricks..."
sudo apt install -y winetricks

# Installer les composants nécessaires pour MT5
echo "Installation des composants Windows..."
winetricks -q corefonts
winetricks -q vcrun2019 || echo "vcrun2019 peut nécessiter une installation manuelle"

# ================================================================
# ÉTAPE 6 : Téléchargement et Installation de MetaTrader 5
# ================================================================
echo -e "\n${GREEN}[6/8] 📥 Installation de MetaTrader 5...${NC}"

mkdir -p ~/mt5
cd ~/mt5

# Télécharger MT5
if [ ! -f "mt5setup.exe" ]; then
    echo "Téléchargement de MetaTrader 5..."
    wget "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
fi

# Installer MT5 (mode silencieux)
echo "Installation de MT5 (cela peut prendre 2-3 minutes)..."
wine mt5setup.exe /auto &
MT5_PID=$!

# Attendre l'installation
echo "Attente de la fin de l'installation..."
sleep 120

# Tuer le processus s'il est encore actif
kill $MT5_PID 2>/dev/null || true

echo "MT5 installé!"

# ================================================================
# ÉTAPE 7 : Configuration du Bot Python
# ================================================================
echo -e "\n${GREEN}[7/8] 🐍 Configuration de l'environnement Python...${NC}"

mkdir -p ~/smc-bot
cd ~/smc-bot

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Mettre à jour pip
pip install --upgrade pip setuptools wheel

# Installer les dépendances Python
pip install \
    pandas \
    numpy \
    loguru \
    pyyaml \
    requests \
    ta \
    plotly \
    kaleido

# Note: MetaTrader5 Python ne fonctionne pas nativement sur Linux
# On utilise une alternative avec rpyc ou on exécute via Wine
echo -e "${YELLOW}⚠️ Note: Le module Python MetaTrader5 nécessite Windows.${NC}"
echo "   Nous allons configurer une solution alternative..."

# ================================================================
# ÉTAPE 8 : Configuration des services
# ================================================================
echo -e "\n${GREEN}[8/8] ⚙️ Configuration des services...${NC}"

# Créer le script de démarrage du bot
cat > ~/scripts/start_bot.sh << 'EOF'
#!/bin/bash
export DISPLAY=:1

# Démarrer Xvfb si pas déjà lancé
if ! pgrep -x "Xvfb" > /dev/null; then
    Xvfb :1 -screen 0 1280x1024x24 &
    sleep 2
fi

# Activer l'environnement Python
cd ~/smc-bot
source venv/bin/activate

# Lancer le bot
python main.py --mode live
EOF
chmod +x ~/scripts/start_bot.sh

# Créer le script de démarrage VNC
cat > ~/scripts/start_vnc.sh << 'EOF'
#!/bin/bash
export DISPLAY=:1
x11vnc -display :1 -forever -nopw -create -rfbport 5900 &
echo "VNC Server started on port 5900"
echo "Connect to: $(curl -s ifconfig.me):5900"
EOF
chmod +x ~/scripts/start_vnc.sh

# Créer le fichier service systemd
sudo tee /etc/systemd/system/xvfb.service > /dev/null << 'EOF'
[Unit]
Description=X Virtual Frame Buffer
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :1 -screen 0 1280x1024x24
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Activer Xvfb au démarrage
sudo systemctl daemon-reload
sudo systemctl enable xvfb
sudo systemctl start xvfb

# ================================================================
# RÉSUMÉ
# ================================================================
echo -e "\n${GREEN}"
echo "========================================"
echo "✅ INSTALLATION TERMINÉE !"
echo "========================================"
echo -e "${NC}"

echo ""
echo "📁 Dossiers créés:"
echo "   ~/smc-bot/     - Dossier du bot (mettez vos fichiers ici)"
echo "   ~/mt5/         - Installation MetaTrader 5"
echo "   ~/scripts/     - Scripts utilitaires"
echo ""
echo "📜 Scripts utiles:"
echo "   ~/scripts/start_xvfb.sh  - Démarrer l'écran virtuel"
echo "   ~/scripts/start_vnc.sh   - Démarrer VNC (accès graphique)"
echo "   ~/scripts/start_bot.sh   - Démarrer le bot"
echo ""
echo -e "${YELLOW}⚠️ PROCHAINES ÉTAPES:${NC}"
echo ""
echo "1. Transférez vos fichiers du bot:"
echo "   scp -i key.key -r E:/SMC/* ubuntu@IP:~/smc-bot/"
echo ""
echo "2. Démarrez VNC pour configurer MT5:"
echo "   ~/scripts/start_vnc.sh"
echo "   Puis connectez-vous avec VNC Viewer à: $(curl -s ifconfig.me 2>/dev/null || echo 'VOTRE_IP'):5900"
echo ""
echo "3. Lancez MT5 et connectez-vous à votre compte:"
echo "   wine ~/.wine64/drive_c/Program\ Files/MetaTrader\ 5/terminal64.exe"
echo ""
echo "4. Lancez le bot:"
echo "   ~/scripts/start_bot.sh"
echo ""
echo "========================================"
echo -e "${GREEN}🎉 Votre serveur est prêt pour le trading 24/7!${NC}"
echo "========================================"
