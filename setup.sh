#!/bin/bash

# Cloudflare Telegram Bot - Setup Script
# This script automates the installation and setup process

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored messages
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Python 3 is installed
check_python() {
    print_info "Checking Python installation..."
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        print_success "Python $PYTHON_VERSION found"
        PYTHON_CMD=python3
    elif command -v python &> /dev/null; then
        PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
        # Check if it's Python 3
        if python -c "import sys; exit(0 if sys.version_info[0] == 3 else 1)"; then
            print_success "Python $PYTHON_VERSION found"
            PYTHON_CMD=python
        else
            print_error "Python 3 is required but Python 2 was found"
            exit 1
        fi
    else
        print_error "Python 3 is not installed. Please install Python 3.8 or higher."
        exit 1
    fi
    
    # Check Python version
    if ! $PYTHON_CMD -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
        print_error "Python 3.8 or higher is required"
        exit 1
    fi
}

# Check if pip is installed
check_pip() {
    print_info "Checking pip installation..."
    if command -v pip3 &> /dev/null; then
        PIP_CMD=pip3
    elif command -v pip &> /dev/null; then
        PIP_CMD=pip
    else
        print_error "pip is not installed. Please install pip."
        exit 1
    fi
    print_success "pip found"
}

# Install dependencies
install_dependencies() {
    print_info "Installing Python dependencies..."
    if [ -f "requirements.txt" ]; then
        $PIP_CMD install -r requirements.txt
        print_success "Dependencies installed"
    else
        print_error "requirements.txt not found"
        exit 1
    fi
}

# Run installation script
run_install_script() {
    print_info "Running installation wizard..."
    if [ -f "install.py" ]; then
        $PYTHON_CMD install.py
        print_success "Configuration completed"
    else
        print_warning "install.py not found. You'll need to configure manually."
        print_info "Create a .env file with the following variables:"
        echo "  TELEGRAM_BOT_TOKEN"
        echo "  ADMIN_USER_IDS"
        echo "  CLOUDFLARE_API_TOKEN"
        echo "  CLOUDFLARE_ZONE_ID"
    fi
}

# Create systemd service file (optional)
create_systemd_service() {
    if [ "$EUID" -eq 0 ]; then
        print_info "Creating systemd service file..."
        SERVICE_FILE="/etc/systemd/system/cloudflare-bot.service"
        WORK_DIR=$(pwd)
        PYTHON_PATH=$(which $PYTHON_CMD)
        
        cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Cloudflare Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORK_DIR
ExecStart=$PYTHON_PATH $WORK_DIR/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
        print_success "Systemd service file created at $SERVICE_FILE"
        print_info "To enable and start the service, run:"
        echo "  sudo systemctl enable cloudflare-bot"
        echo "  sudo systemctl start cloudflare-bot"
    else
        print_info "Skipping systemd service creation (requires root)"
    fi
}

# Main setup function
main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                                                              ║"
    echo "║     🤖 Cloudflare Telegram Bot - Setup Script             ║"
    echo "║                                                              ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    check_python
    check_pip
    install_dependencies
    run_install_script
    
    echo ""
    print_success "Setup completed!"
    echo ""
    print_info "Next steps:"
    echo "  1. Review your .env file to ensure all settings are correct"
    echo "  2. Run the bot: $PYTHON_CMD bot.py"
    echo "  3. Or run in background: nohup $PYTHON_CMD bot.py > output.log 2>&1 &"
    echo ""
    
    read -p "Do you want to create a systemd service file? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        create_systemd_service
    fi
    
    echo ""
    print_success "All done! You can now start the bot."
}

# Run main function
main

