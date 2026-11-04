Рабочая графика из `documentation/brandbook_minecraft/minecraft_assets`.
Назначение файлов: `documentation/minecraft-assets.md`.

Файлы `world-light.webp`, `world-dark.webp`, `foreground-light.webp`,
`foreground-dark.webp`, `hero-light.webp`, `hero-dark.webp` подключаются автоматически
при наличии. После добавления: collectstatic и перезапуск приложения.
`frames_flat/*/{corner-*,edge-*}.png` — текущие облегчённые рамки: фиксированные углы,
естественное повторение сторон. `frames/*/9slice.png` сохранены для совместимости.
Рамка занимает настоящую границу карточки: таблица и hover не могут её перекрыть.
`avatars/` — десять постоянных вариантов для псевдослучайного выбора по аккаунту.
`scene/` — визуально проверенные элементы новой поставки с осмысленными именами;
карта исходных файлов есть в `documentation/minecraft-assets.md`. Дневное дерево,
цветы и деревянная опора ночью заменяются обсидианом/кристаллами; лицо аккаунта
и смысл иконок остаются прежними. Reduced-motion отключает движение декора.
