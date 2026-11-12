# Установка UniMate Studio

Эта инструкция — как развернуть проект на новом компьютере с нуля. Она объединяет два
компонента: **UniMate** (text-to-motion, Python 3.10) и **студию AssetFurnace**
(картинка/фраза → 3D → риг → анимация, Python 3.11).

```text
фраза / картинка → 3D-модель → Finish → Rig → UniMate motion → анимированный GLB
```

## 1. Требования

| Что | Требование |
|---|---|
| ОС | Windows или Linux (**macOS не поддерживается** — UniMate его не поддерживает) |
| GPU | NVIDIA (CUDA), драйвер **575+** (иначе Pixal3D придётся компилировать) |
| Диск | ~30 ГБ свободного места под все веса |
| Дополнительно | `uv` (установщик студии предложит поставить сам), `git` (для Linux-установщика) |

## 2. Получить код

Скопируйте папку проекта целиком, **без** папок, которые всё равно пересоздаются:

- **исключить:** `.venv`, `.venv-studio`, `outputs/`, `output/`, `models/`, `vendor/`, `dataset/`
- **нужно:** весь остальной код + установщики (`install.bat`, `install.sh`,
  `install_studio.ps1`, `install_studio.sh`, `lab`, `lab.cmd`, `run.bat`)

Если репозиторий закоммичен — достаточно `git clone`.

## 3. Установка

Два окружения, потому что они используют разные версии numpy:

| Окружение | Python | Что в нём работает | Установщик |
|---|---|---|---|
| `.venv` | 3.10 | UniMate: сэмплинг движения, `rig_preprocess`, анимация меша, WebUI | `install.bat` / `install.sh` — скачивает чекпойнт (~6 ГБ) |
| `.venv-studio` | 3.11 | Студия, движки, риг, MCP | `install_studio.ps1` / `install_studio.sh` — только пакеты |

### Windows

```powershell
install.bat            # UniMate: .venv + чекпойнт (спросит перед ~6 ГБ)
powershell -ExecutionPolicy ByPass -File install_studio.ps1   # студия: .venv-studio
.\lab                  # открыть студию в браузере
```

### Linux

```bash
bash install.sh
bash install_studio.sh
./lab
```

## 4. Первый запуск

В студии (`http://127.0.0.1:8777`):

1. **Setup & Status** → нажать **Set up** у **Pixal3D** (~8.4 ГБ, спросит размер и лицензию).
2. Поставить **Blender 4.2+** самостоятельно (нужен для Finish — низкополигональной
   чистки и Pixel Match). Карточка Blender на той же странице покажет, найден ли он.
3. Карточка **UniMate** уже должна быть зелёной (✓ ready) — это значит, что чекпойнт
   из шага 3 на месте.

Дальше: **+ Create** → «Start from: An idea» → «I want: A character moved by text» →
опишите персонажа и напишите промпт движения (например `An object walks forward.`) →
**Make it**.

## 5. Где хранятся модели

По умолчанию — всё внутри проекта:

```
models/
├── huggingface/   ← все HF-модели (TRELLIS.2, Hunyuan3D, Qwen, …)
├── u2net/         ← модель вырезания фона
└── <движок>/      ← Pixal3D и другие
```

Чекпойнт UniMate — в `outputs/unimate_uniml3d_f60_v3/` (его ставит `install.bat`).

Сменить место — на странице **Setup & Status → Models folder**, или переменной
окружения `ASSETFURNACE_MODELS=<путь>`.

## 6. Запуск

- `run.bat` — меню выбора: **1** = студия, **2** = WebUI (старый Gradio для движения по
  готовому ригу).
- `.\lab` / `./lab` — сразу студия.
- `.\lab mcp` — MCP-сервер для агентов (Claude Code и т.п.).

## 7. Примечания

- **Pixal3D** — единственный 3D-движок, работающий на Windows+NVIDIA. TRELLIS.2 и
  Hunyuan3D-2.1 — только Linux, их Setup честно откажет на Windows.
- **Первый запуск UniMate** подтягивает текстовый энкодер `flan-t5-base` с Hugging Face
  (нужен интернет).
- **Веса не качаются молча**: каждая кнопка Setup и `install.bat` сначала называют
  размер и спрашивают согласие.
- **Лицензии**: код UniMate — MIT, его чекпойнт — CC BY-NC 4.0 (выход движения
  помечается в `.provenance.json` как не для коммерческого использования); студия —
  Apache-2.0 (`LICENSE-ASSETFURNACE-APACHE` + `NOTICE`).

Проблемы при установке — `run_webui.bat` / `.\lab` выводят ошибку с подсказкой, что
именно отсутствует.
