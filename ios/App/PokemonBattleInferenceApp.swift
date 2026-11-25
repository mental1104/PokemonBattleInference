import SwiftUI

/// 原生 iPhone/iPad 入口；一次创建应用模型，数据与计算交由独立 actor。
@main @MainActor struct PokemonBattleInferenceApp: App {
    @StateObject private var model = AppModel()
    /// 加载实际离线库后显示界面，不创建展示用假数据源。
    var body: some Scene {
        WindowGroup { RootView(model: model).task { await model.start() } }
    }
}
