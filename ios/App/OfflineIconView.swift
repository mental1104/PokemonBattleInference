import SwiftUI
import UIKit
import PokemonAppSupport

/// 用本地朱紫PNG识别宝可梦、道具和属性；没有图标的条目仍保留真实名称，绝不借用其他宝可梦图片。
@MainActor struct OfflineIconView: View {
    let icon: BundledIcon
    let label: String
    var size: CGFloat = 40

    /// icon是稳定知识身份，label供无障碍阅读，size为显示尺寸，不改变打包的原始PNG。
    var body: some View {
        Group {
            if let name = icon.resourceName, let url = BundledIcons.url(for: icon),
               let image = UIImage(contentsOfFile: url.path) {
                Image(uiImage: image).resizable().scaledToFit()
                    .accessibilityLabel("\(label)图标")
                    .accessibilityIdentifier("offline-icon-\(name)")
            } else if icon != .item(.none) {
                Image(systemName: "questionmark.circle").foregroundStyle(.secondary)
                    .accessibilityLabel("\(label)，未收录图标")
            }
        }.frame(width: size, height: size)
    }
}
