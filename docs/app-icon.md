# App 图标

`ios/App/Assets.xcassets/AppIcon.appiconset/AppIcon.png` 是正式1024×1024、不含透明通道的PNG。Xcode资产目录从同一母图生成iPhone/iPad所需尺寸；工程显式选择`AppIcon`，不预先画圆角。

2026-11-24按用户要求使用内置`imagegen`生成，精灵球轮廓结合三条概率分支，使用深蓝背景、紫色与青色。生成母图1254×1254，使用macOS`sips`缩为标准1024方形，仅作资源封装；未改图案。原始图保存在本次生成记录，正式消费资源已保存到仓库。

最终生成提示词：

> Use case: logo-brand. Asset type: production iOS app icon for a native Pokémon battle probability calculator called 宝可梦对战推演. Create ONE polished square 1024x1024 PNG app-icon master, full bleed and fully opaque. Subject: a bold, beautifully simple circular capture-ball inspired emblem integrated with three connected probability-tree nodes, suggesting tactical battle simulation and exact branching outcomes. A white central circular button is the visual anchor; two crisp curved halves in luminous indigo and cyan, with a small vivid violet accent. Backdrop: deep midnight blue with a very subtle indigo gradient. Style: refined contemporary app icon, vector-clean silhouettes with restrained dimensional shading, excellent contrast, recognizable at 40px. Centered, balanced, emblem occupies about 70% of the square. Design the actual icon artwork only, edge-to-edge square background; iOS applies the rounded-corner mask. No text, no letters, no numbers, no border, no external drop shadow, no mockup, no phone, no watermark, no extra illustrations.
