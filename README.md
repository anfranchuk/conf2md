# Экспорт Confluence

Два варианта выгрузки аналитики в Markdown.

## Вариант 1: через API Confluence

Экспортирует страницу по `page-id`, все подстраницы и вложения.

Установка:
```
pip install -r requirements.txt
```

Запуск:
```
python export_confluence.py --url "https://confluence.example.com" --username "login" --password "pass" --page-id 123456 --out "C:\path\to\out"
```

## Вариант 2: из HTML-экспорта

Конвертирует HTML-экспорт (папка со страницами) в Markdown и копирует вложенные файлы.

Запуск:
```
python export_html_to_md.py --input "C:\path\to\html-export" --output "C:\path\to\md-out"
```

### Примечания

- Ссылки на страницы переписываются на локальные `.md`.
- Вложения копируются с сохранением структуры.
- В Confluence Cloud обычно нужен API token вместо пароля.
