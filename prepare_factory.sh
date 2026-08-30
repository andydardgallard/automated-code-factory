#!/usr/bin/env bash
# =============================================================================
# prepare_factory.sh — подготовка проекта к запуску Code Factory одним действием.
#
# Назначение: скопировать фабрику (.agents/) в проект, настроить .gitignore,
# при необходимости инициализировать git-репозиторий, создать launcher `start.sh`
# (он сам выставляет нужные переменные окружения) и проверить готовность.
#
# Использование:
#   ./prepare_factory.sh <путь-к-проекту>
#
# Пример:
#   ./prepare_factory.sh /home/adar/ai-factories/my-test-project
#
# После подготовки достаточно одного действия:
#   cd <путь-к-проекту> && ./start.sh          # интерактивно (в чате: /skill:code-factory)
#   cd <путь-к-проекту> && ./start.sh --auto   # полностью автономно
#
# Скрипт НЕ коммитит ничего. Все шаги безопасны и идемпотентны.
# =============================================================================
set -euo pipefail

# --- Пути -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FACTORY_SRC="$SCRIPT_DIR/.agents"          # готовая фабрика (этот репозиторий)
PROJECT_DIR="${1:-}"

# --- Цвета ------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { printf "${GREEN}%s${NC}\n" "$*"; }
warn()  { printf "${YELLOW}%s${NC}\n" "$*"; }
err()   { printf "${RED}%s${NC}\n" "$*" >&2; }

# --- Проверка аргумента ------------------------------------------------------
if [[ -z "$PROJECT_DIR" ]]; then
    err "Укажите путь к проекту:  ./prepare_factory.sh <путь-к-проекту>"
    exit 1
fi
if [[ ! -d "$PROJECT_DIR" ]]; then
    err "Папка проекта не найдена: $PROJECT_DIR"
    exit 1
fi
if [[ ! -d "$FACTORY_SRC" ]]; then
    err "Не найдена фабрика: $FACTORY_SRC (запускайте скрипт из корня репозитория фабрики)"
    exit 1
fi

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
info "==> Подготовка проекта: $PROJECT_DIR"

# --- 1. Git-репозиторий ------------------------------------------------------
if [[ -d "$PROJECT_DIR/.git" ]]; then
    info "    Git: репозиторий уже существует ✓"
else
    warn "    Git: репозитория нет — создаю git init"
    git -C "$PROJECT_DIR" init -b main
fi

# --- 2. Копирование фабрики --------------------------------------------------
if [[ "$PROJECT_DIR" == "$SCRIPT_DIR" ]]; then
    warn "    Проект — сам репозиторий фабрики: .agents/ уже на месте, пропускаю копирование."
elif [[ -d "$PROJECT_DIR/.agents" ]]; then
    info "    .agents/ уже существует — обновляю содержимое фабрики (фабрика — source of truth)"
    # Перезаписываем все файлы фабрики актуальными версиями. Пользовательские файлы,
    # которых нет в фабрике, остаются нетронутыми (cp не удаляет лишнее).
    cp -r "$FACTORY_SRC"/. "$PROJECT_DIR/.agents/"
else
    info "    Фабрика: копирую .agents/ → $PROJECT_DIR/.agents"
    cp -r "$FACTORY_SRC" "$PROJECT_DIR/.agents"
fi

# --- 3. Launcher --------------------------------------------------------------
LAUNCHER="$PROJECT_DIR/start.sh"
cat > "$LAUNCHER" <<'EOF'
#!/usr/bin/env bash
# Launcher Code Factory — создан prepare_factory.sh. Запускайте без лишних команд:
#   ./start.sh          — интерактивно (в чате: /skill:code-factory)
#   ./start.sh --auto   — полностью автономно
set -euo pipefail
# Разделение моделей сабагентов (primary/secondary) включается здесь автоматически.
export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1
exec kimi "$@"
EOF
chmod +x "$LAUNCHER"
info "    Launcher: создан $LAUNCHER"

# --- 4. .gitignore -----------------------------------------------------------
# Примечание: .gitignore влияет только на git-трекинг, но не на доступ к файлам
# на диске. Игнорирование .agents/ не ломает чтение/запись данных фабрики
# (кэш, история, контекст) — фабрика работает с .agents/ напрямую через файловую
# систему, а не через git.
GITIGNORE="$PROJECT_DIR/.gitignore"
NEED_GITIGNORE=false
for pat in ".agents/" ".code-factory/" "__pycache__/" "*.pyc"; do
    if [[ -f "$GITIGNORE" ]] && grep -qF "$pat" "$GITIGNORE"; then
        :
    else
        NEED_GITIGNORE=true
    fi
done

if [[ "$NEED_GITIGNORE" == true ]]; then
    warn "    .gitignore: добавляю служебные паттерны фабрики"
    {
        [[ -f "$GITIGNORE" ]] && echo ""
        echo "# --- Code Factory (auto-added by prepare_factory.sh) ---"
        echo ".agents/"
        echo ".code-factory/"
        echo "__pycache__/"
        echo "*.pyc"
    } >> "$GITIGNORE"
fi

# --- 5. Проверка готовности --------------------------------------------------
echo ""
info "==> Проверка готовности:"
echo "    • .agents/:            $([ -f "$PROJECT_DIR/.agents/skills/code-factory/SKILL.md" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • start.sh:            $([ -x "$LAUNCHER" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • .git/:               $([ -d "$PROJECT_DIR/.git" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • .gitignore:          $(grep -qF '.agents/' "$PROJECT_DIR/.gitignore" 2>/dev/null && grep -qF '.code-factory/' "$PROJECT_DIR/.gitignore" 2>/dev/null && echo 'OK ✓ (.agents/ + .code-factory/)' || echo 'нет .agents/ или .code-factory/ ✗')"
echo "    • git status:"
git -C "$PROJECT_DIR" status --short | head -20 || true
[[ -z "$(git -C "$PROJECT_DIR" status --short)" ]] && echo "      (чистое дерево)"
echo ""

info "==> Готово! Запуск фабрики — одно действие:"
echo "    cd $PROJECT_DIR"
echo "    ./start.sh            # в чате: /skill:code-factory"
echo "    ./start.sh --auto     # полностью автономно"
echo ""
echo "    Launcher сам выставляет KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1 —"
echo "    дополнительных export-команд запоминать не нужно."
