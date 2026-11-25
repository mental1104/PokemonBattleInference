import Foundation

/// 离线图标身份使用真实知识编号和现有道具枚举，不包含图片下载或战斗规则。
public enum BundledIcon: Hashable, Sendable {
    case pokemon(Int64)
    case item(ItemRule)
    case elementType(Int64)

    /// 返回显式图标包的唯一文件名；无道具和非法编号无资源，未收录编号由URL查找返回nil。
    public var resourceName: String? {
        switch self {
        case let .pokemon(id): return id > 0 ? "pokemon-\(id)" : nil
        case .item(.none): return nil
        case let .item(item): return "item-" + item.rawValue.replacingOccurrences(of: "_", with: "-")
        case let .elementType(id): return id > 0 ? "type-\(id)" : nil
        }
    }
}

/// 只定位SPM捆绑的精选PNG；任何缺失都明确返回nil，不访问网络或读取用户知识库。
public enum BundledIcons {
    /// - Parameter icon: 当前宝可梦/道具/属性身份，必须对应显式打包项。
    /// - Returns: 只读包内URL；未收录和无道具返回nil，调用方保留名称并显示明确占位。
    public static func url(for icon: BundledIcon) -> URL? {
        guard let name = icon.resourceName else { return nil }
        return Bundle.module.url(forResource: name, withExtension: "png", subdirectory: "Icons")
    }
}
