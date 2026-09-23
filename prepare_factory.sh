#!/usr/bin/env bash
# =============================================================================
# prepare_factory.sh — подготовка проекта к запуску Code Factory одним действием.
#
# Назначение: скопировать фабрику (.agents/) в проект, завести память ИМЕННО этого
# проекта (`memory/` — долгосрочная память целевого проекта: журнал
# `memory/change-log.md` + сводка `memory/summary.md`), настроить .gitignore, при
# необходимости инициализировать git-репозиторий, создать launcher `start.sh` (он сам
# выставляет нужные переменные окружения) и проверить готовность.
#
# Где живёт память и как называется проект:
#   * `memory/` создаётся В КОРНЕ РАЗВЁРТЫВАНИЯ — в том каталоге, который передан этому
#     скрипту; базовое имя проекта при развёртывании = basename этого каталога.
#   * Если `repo_path` задачи указывает на ПОДКАТАЛОГ корня развёртывания, главный агент
#     заводит память явно, назвав проект:
#       memory_project.py init --repo <корень развёртывания> --project <basename разрешённого repo_path>
#     Имя фиксируется в объявлении `project:` сводки `memory/summary.md` (и в `project:`
#     каждой новой записи журнала), поэтому обе стороны называют проект одинаково.
# Существующая память проекта НИКОГДА не перезаписывается: недостающие файлы
# создаются, а уже имеющиеся (история прогонов проекта) остаются нетронутыми. Если
# память объявлена за ДРУГОЙ проект или смешивает проекты — только предупреждение
# (скрипт всё равно завершается с exit 0).
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

# --- Интерпретатор Python ----------------------------------------------------
# Нужен для скриптов фабрики (память проекта). Может быть не найден — это не ошибка.
# Стаб `python3` из Microsoft Store (Windows) существует как файл, но не работает,
# поэтому берём первый РАБОЧИЙ интерпретатор (приоритет: python3, затем python).
PY_BIN="$(command -v python3 || command -v python || true)"
if [[ -n "$PY_BIN" ]] && ! "$PY_BIN" -c 'pass' >/dev/null 2>&1; then
    PY_BIN=""
    for py_cand in python3 python; do
        py_path="$(command -v "$py_cand" || true)"
        if [[ -n "$py_path" ]] && "$py_path" -c 'pass' >/dev/null 2>&1; then
            PY_BIN="$py_path"
            break
        fi
    done
fi

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
    # `git init -b main` есть только с git 2.28; на старых git делаем init + symbolic-ref
    # (unborn-ветка переименовывается без создания коммита).
    if ! git -C "$PROJECT_DIR" init -b main 2>/dev/null; then
        git -C "$PROJECT_DIR" init
        git -C "$PROJECT_DIR" symbolic-ref HEAD refs/heads/main
    fi
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

# --- 3. Память проекта --------------------------------------------------------
# memory/ — долгосрочная память ТОГО проекта, над которым работает фабрика. Каталог
# памяти всегда лежит В КОРНЕ РАЗВЁРТЫВАНИЯ ($PROJECT_DIR), а базовое имя проекта при
# развёртывании = basename этого каталога. Если `repo_path` задачи указывает на
# ПОДКАТАЛОГ корня развёртывания, главный агент фиксирует имя проекта явно:
#   memory_project.py init --repo <корень развёртывания> --project <basename разрешённого repo_path>
# (имя попадает в `project:` записей журнала и в объявление `project:` сводки).
# Единственный писатель журнала — главный агент фабрики, поэтому здесь только
# создаются ОТСУТСТВУЮЩИЕ файлы: существующая память (история прогонов проекта) никогда
# не перезаписывается и не изменяется — проверяется лишь её принадлежность.
MEMORY_DIR="$PROJECT_DIR/memory"
MEM_DIR_SCRIPT="$PROJECT_DIR/.agents/skills/code-factory/scripts/memory_project.py"
MEM_STATE="absent"          # created | ok | mixed | other | unavailable
MEM_PROJECT=""              # имя проекта (состояние created)
MEM_OWNER=""                # владелец памяти по данным memory_project.py check
MEM_CHECK_OUT=""
# Ожидаемое имя проекта = basename корня развёртывания. Считаем один раз и устойчиво
# к set -euo pipefail: ошибка интерпретатора/скрипта не должна прерывать развёртывание.
MEM_NAME_EXPECT="$("$PY_BIN" "$MEM_DIR_SCRIPT" name --repo "$PROJECT_DIR" 2>/dev/null || true)"

if [[ ! -f "$MEMORY_DIR/change-log.md" || ! -f "$MEMORY_DIR/summary.md" ]]; then
    if [[ -n "$PY_BIN" && -f "$MEM_DIR_SCRIPT" ]]; then
        if MEM_INIT_OUT="$("$PY_BIN" "$MEM_DIR_SCRIPT" init --repo "$PROJECT_DIR" 2>&1)"; then
            MEM_STATE="created"
            MEM_PROJECT="$("$PY_BIN" "$MEM_DIR_SCRIPT" name --repo "$PROJECT_DIR" 2>/dev/null || true)"
            info "    Память проекта: создана — $MEMORY_DIR (проект ${MEM_PROJECT:-?})"
            printf '%s\n' "$MEM_INIT_OUT" | sed 's/^/      /'
        else
            # Причина сбоя — последняя непустая строка вывода (у падения интерпретатора это
            # строка исключения, а не весь traceback: сырой стек в предупреждении только мешает).
            # Пустой вывод даёт пустую причину — её подменяет «без вывода».
            MEM_INIT_REASON="$(printf '%s\n' "$MEM_INIT_OUT" | awk 'NF{last=$0}END{print last}')"
            warn "    Память проекта: не удалось создать — ${MEM_INIT_REASON:-без вывода}"
            warn "    Фабрика создаст её при первом обращении к проекту."
        fi
    else
        MEM_STATE="unavailable"
        if [[ -z "$PY_BIN" ]]; then
            warn "    Память проекта: не создана — python не найден"
        else
            warn "    Память проекта: не создана — нет скрипта $MEM_DIR_SCRIPT"
        fi
        warn "    Фабрика создаст её при первом обращении к проекту."
    fi
elif [[ -n "$PY_BIN" && -f "$MEM_DIR_SCRIPT" ]]; then
    # Память уже есть: ничего не меняем (история проекта не перезаписывается). Проверяем
    # три исхода: журнал смешивает проекты | память объявлена за ДРУГОЙ проект | всё ок.
    # `|| MEM_CHECK_RC=$?` не роняет скрипт: любое состояние — только предупреждение.
    MEM_CHECK_RC=0
    MEM_CHECK_OUT="$("$PY_BIN" "$MEM_DIR_SCRIPT" check --repo "$PROJECT_DIR" 2>&1)" || MEM_CHECK_RC=$?
    MEM_OWNER=""
    if [[ "$MEM_CHECK_OUT" =~ belongs\ to\ project\ \'([^\']+)\' ]]; then
        MEM_OWNER="${BASH_REMATCH[1]}"
    elif [[ "$MEM_CHECK_OUT" =~ declares\ project\ \'([^\']+)\' ]]; then
        MEM_OWNER="${BASH_REMATCH[1]}"
    fi
    if [[ "$MEM_CHECK_OUT" == *"mixes projects"* ]]; then
        MEM_STATE="mixed"
        warn "    Память проекта: НЕСОГЛАСОВАНА — в памяти записи разных проектов ($MEM_CHECK_OUT)"
        warn "    Проверьте принадлежность: поле project: в записях должно совпадать с проектом."
    elif [[ "$MEM_CHECK_OUT" == *"expected"* ]] \
      || { [[ -n "$MEM_OWNER" ]] && [[ "$MEM_OWNER" != "$MEM_NAME_EXPECT" ]] \
           && [[ "$MEM_OWNER" != "(legacy, no project field)" ]]; } \
      || [[ "$MEM_CHECK_RC" -ne 0 ]]; then
        # Память принадлежит (или объявлена за) ДРУГОЙ проект — разворачиваемся не туда.
        MEM_STATE="other"
        warn "    Память проекта: ПРОВЕРИТЬ — память объявлена за проект '${MEM_OWNER:-?}', а фабрика разворачивается в каталоге '$MEM_NAME_EXPECT' ($MEM_CHECK_OUT)"
        warn "    Проверьте, что это тот же проект: поле project: в записях memory/change-log.md."
    else
        MEM_STATE="ok"
        info "    Память проекта: на месте — $MEM_CHECK_OUT"
    fi
else
    MEM_STATE="unavailable"
    if [[ -z "$PY_BIN" ]]; then
        warn "    Память проекта: есть, но не проверена — python не найден"
    else
        warn "    Память проекта: есть, но не проверена — нет скрипта $MEM_DIR_SCRIPT"
    fi
fi

# --- 4. Launcher --------------------------------------------------------------
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

# --- 5. .gitignore -----------------------------------------------------------
# Примечание: .gitignore влияет только на git-трекинг, но не на доступ к файлам
# на диске. Игнорирование .agents/ не ломает чтение/запись данных фабрики
# (кэш, история, контекст) — фабрика работает с .agents/ напрямую через файловую
# систему, а не через git.
GITIGNORE="$PROJECT_DIR/.gitignore"
# Точное совпадение строки (-x): подстрочный матч считал паттерн добавленным, хотя в
# .gitignore была лишь похожая строка. `tr -d '\r'` — чтобы CRLF-файл (Windows) не
# ломал проверку и паттерны не дублировались при повторном запуске.
gitignore_has() {
    [[ -f "$GITIGNORE" ]] && tr -d '\r' < "$GITIGNORE" | grep -qxF "$1"
}
NEED_GITIGNORE=false
for pat in ".agents/" ".code-factory/" "__pycache__/" "*.pyc" ".env" ".env.*" "*.env" "*.pem" "*.key"; do
    gitignore_has "$pat" || NEED_GITIGNORE=true
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
        echo ".env"
        echo ".env.*"
        echo "*.env"
        echo "*.pem"
        echo "*.key"
    } >> "$GITIGNORE"
fi

# --- 6. Проверка готовности --------------------------------------------------
# Строку про память собираем из состояния шага 3 (повторный init не запускаем). Три
# различимых состояния: ok — память принадлежит этому проекту; mixed — записи разных
# проектов; other — память объявлена за другой проект (разворачиваемся не туда).
case "$MEM_STATE" in
    created)  MEM_LINE="создана ✓ (проект ${MEM_PROJECT:-?})" ;;
    ok)
        if [[ "$MEM_CHECK_OUT" =~ project\ \'([^\']+)\'\ \(([0-9]+)\ entries\) ]]; then
            MEM_NAME="${BASH_REMATCH[1]}"
            MEM_COUNT="${BASH_REMATCH[2]}"
            # Память без признака проекта (ни project: в записях, ни объявления в сводке):
            # подставляем имя проекта по basename корня развёртывания.
            if [[ "$MEM_NAME" == "(legacy, no project field)" ]]; then
                MEM_NAME="$("$PY_BIN" "$MEM_DIR_SCRIPT" name --repo "$PROJECT_DIR" 2>/dev/null || echo '?')"
            fi
            MEM_LINE="OK ✓ (проект $MEM_NAME, $MEM_COUNT записей)"
        else
            MEM_LINE="OK ✓"
        fi
        ;;
    mixed)    MEM_LINE="НЕСОГЛАСОВАНА ✗ (в памяти записи разных проектов — проверьте project:)" ;;
    other)    MEM_LINE="ПРОВЕРИТЬ ✗ (объявлен проект ${MEM_OWNER:-?}, разворачиваем в ${MEM_NAME_EXPECT:-?})" ;;
    unavailable)
        if [[ -z "$PY_BIN" ]]; then
            MEM_LINE="не проверено (нет python)"
        else
            MEM_LINE="не проверено (нет memory_project.py)"
        fi
        ;;
    *)        MEM_LINE="ОТСУТСТВУЕТ ✗" ;;
esac
echo ""
info "==> Проверка готовности:"
echo "    • .agents/:            $([ -f "$PROJECT_DIR/.agents/skills/code-factory/SKILL.md" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • start.sh:            $([ -x "$LAUNCHER" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • .git/:               $([ -d "$PROJECT_DIR/.git" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • .gitignore:          $(gitignore_has '.agents/' && gitignore_has '.code-factory/' && echo 'OK ✓ (.agents/ + .code-factory/)' || echo 'нет .agents/ или .code-factory/ ✗')"
echo "    • memory/:              $MEM_LINE"
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
