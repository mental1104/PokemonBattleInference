import XCTest
import UIKit

/// 黑盒操作真实 App；每个测试在独立 UITesting 用户库中首装，重启保留该库。
final class PokemonAppUITests: XCTestCase {
    @MainActor private var app: XCUIApplication!
    /// 启动时只清理测试目录，不触碰常规用户的配置和知识包。
    @MainActor private func launchCleanApp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--reset-testing-store"]
        app.launch()
        let ready = tab("计算").waitForExistence(timeout: 30)
        if !ready { capture("launch-failure") }
        XCTAssertTrue(ready, "Application must finish real knowledge installation")
    }
    /// 首装中文搜索命中 SQLite 的巨钳螳螂记录，进入详情核对真实属性。
    @MainActor func testFirstInstallChineseKnowledgeSearch() {
        launchCleanApp()
        // iPad 竖屏的真实 NavigationSplitView 先显示详情；通过侧栏按钮打开查询列表。
        if !app.searchFields.firstMatch.waitForExistence(timeout: 2) {
            let sidebar = app.buttons["ToggleSidebar"].firstMatch
            XCTAssertTrue(sidebar.waitForExistence(timeout: 10), "Collapsed catalog must provide a sidebar button")
            sidebar.tap()
        }
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 10), "Knowledge search must exist")
        search.tap(); search.typeText("巨钳螳螂")
        let row = app.buttons["pokemon-212"]
        // NavigationLink 在不同 iOS 版本可暴露为 button 或 other，使用任意类型标识定位。
        let item = row.exists ? row : app.descendants(matching: .any)["pokemon-212"].firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 10), "Bundled database must return Scizor")
        item.tap()
        XCTAssertTrue(app.staticTexts["scizor"].waitForExistence(timeout: 10), "Detail must read real identifier")
        XCTAssertTrue(app.images["offline-icon-pokemon-212"].waitForExistence(timeout: 10), "Scizor detail must render its bundled Scarlet Violet icon")
        capture("first-install-knowledge")
    }
    /// 首装在未配置服务器时选择生命宝珠，真实界面必须呈现随包道具PNG，不能只测试资源存在。
    @MainActor func testFirstInstallHeldItemIcon() {
        launchCleanApp()
        selectTab("计算")
        let picker = app.descendants(matching: .any)["attacker-item-picker"].firstMatch
        reveal(picker)
        XCTAssertTrue(picker.waitForExistence(timeout: 10), "Held-item picker must exist")
        picker.tap()
        let option = app.buttons["生命宝珠"].firstMatch
        let value = option.exists ? option : app.staticTexts["生命宝珠"].firstMatch
        XCTAssertTrue(value.waitForExistence(timeout: 10), "Life Orb must be a supported item option")
        value.tap()
        let image = app.images["offline-icon-item-life-orb"].firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 10), "Selected held item must render its bundled icon")
        XCTAssertTrue(app.windows.firstMatch.frame.intersects(image.frame), "The selected item icon must be visible")
        capture("first-install-held-item-icon")
    }
    /// 首装直接在离线图鉴切换招式、中文搜索并进入真实SQLite详情，避免仅证明宝可梦查询可用。
    @MainActor func testFirstInstallChineseMoveSearch() {
        launchCleanApp()
        if !app.searchFields.firstMatch.waitForExistence(timeout: 2) {
            let sidebar = app.buttons["ToggleSidebar"].firstMatch
            XCTAssertTrue(sidebar.waitForExistence(timeout: 10), "Collapsed catalog must provide a sidebar button")
            sidebar.tap()
        }
        let mode = app.segmentedControls.buttons["招式"]
        XCTAssertTrue(mode.waitForExistence(timeout: 10), "Offline catalog must expose move lookup")
        mode.tap()
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap(); search.typeText("子弹拳")
        let move = app.descendants(matching: .any)["move-418"].firstMatch
        XCTAssertTrue(move.waitForExistence(timeout: 10), "Bundled database must return Bullet Punch")
        move.tap()
        XCTAssertTrue(app.staticTexts["bullet-punch"].waitForExistence(timeout: 10))
        // 两端真实附件均显示LabeledContent合并为“威力, 40”；完整字段精确匹配，不能只查独立数值。
        let power = app.staticTexts["威力, 40"]
        reveal(power)
        XCTAssertTrue(power.waitForExistence(timeout: 10), "Move detail must show the real power")
        XCTAssertEqual(power.label, "威力, 40")
        capture("first-install-move-detail")
    }
    /// 默认输入通过真实 Core 返回共享向量；麻痹重算体现输入绑定确实进入引擎。
    @MainActor func testOfflineDamageExactKOAndParalysis() {
        launchCleanApp()
        selectTab("计算")
        reveal(app.buttons["calculate-offline"]); app.buttons["calculate-offline"].tap()
        let damage = metric("damage-range")
        reveal(damage)
        XCTAssertTrue(damage.waitForExistence(timeout: 15), "Native result must appear")
        XCTAssertEqual(damage.label, "伤害"); XCTAssertEqual(damage.value as? String, "99–117")
        // Form 各结果行独立懒加载；上一行出现不保证 KO 或速度已经进入无障碍树。
        reveal(metric("two-hit-probability"))
        XCTAssertEqual(metric("two-hit-probability").value as? String, "123/128")
        reveal(metric("attacker-speed"))
        XCTAssertEqual(metric("attacker-speed").value as? String, "85")
        capture("offline-damage-exact-ko")
        let paralysis = app.switches["attacker-paralyzed"]
        reveal(paralysis, upward: false)
        XCTAssertEqual(paralysis.value as? String, "0")
        capture("before-paralysis-toggle")
        // SwiftUI Form 暴露362pt整行Switch和51pt的内层UISwitch；真正的用户操作目标是内层开关。
        let control = paralysis.switches.firstMatch
        XCTAssertTrue(control.exists && control.isHittable, "Native toggle control must be visible")
        control.tap()
        waitForValue(paralysis, value: "1")
        capture("after-paralysis-toggle")
        reveal(app.buttons["calculate-offline"]); app.buttons["calculate-offline"].tap()
        reveal(metric("attacker-speed"))
        XCTAssertTrue(metric("attacker-speed").waitForExistence(timeout: 15))
        waitForValue(metric("attacker-speed"), value: "42")
        XCTAssertEqual(metric("attacker-speed").value as? String, "42")
        capture("paralysis-speed")
    }
    /// 修改名称后保存并杀进程重启；SQLite恢复的同一配置必须还能实际离线重算，再检查iPad横屏。
    @MainActor func testSaveRestartAndEditConfiguration() {
        launchCleanApp()
        selectTab("计算")
        let name = app.textFields["configuration-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 10)); name.tap()
        // 使用屏幕上实际编辑后的完整名称验证重启，而不依赖键盘语言的 Select All 菜单。
        name.typeText(" CI saved configuration\n")
        let edited = name.value as? String ?? ""
        XCTAssertTrue(edited.contains("CI saved configuration"))
        app.swipeUp()
        reveal(app.buttons["save-configuration"]); app.buttons["save-configuration"].tap()
        // Form 懒加载，新增成功提示可能在可见按钮下方；滚动后仍严格检查成功和重启后的完整名称。
        reveal(app.staticTexts["configuration-save-status"])
        XCTAssertTrue(app.staticTexts["configuration-save-status"].waitForExistence(timeout: 10))
        app.terminate(); app.launchArguments = ["--ui-testing"]; app.launch()
        selectTab("配置")
        let saved = app.buttons.containing(.staticText, identifier: edited).firstMatch
        XCTAssertTrue(saved.waitForExistence(timeout: 10), "Saved configuration must survive process restart")
        capture("saved-after-restart")
        saved.tap()
        XCTAssertEqual(app.textFields["configuration-name"].value as? String, edited)
        reveal(app.buttons["calculate-offline"]); app.buttons["calculate-offline"].tap()
        reveal(metric("damage-range"))
        XCTAssertTrue(metric("damage-range").waitForExistence(timeout: 15))
        XCTAssertEqual(metric("damage-range").value as? String, "99–117")
        reveal(metric("two-hit-probability"))
        XCTAssertEqual(metric("two-hit-probability").value as? String, "123/128")
        capture("offline-after-restart")
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCUIDevice.shared.orientation = .landscapeLeft
            XCTAssertGreaterThan(app.frame.width, app.frame.height, "iPad editor must support landscape")
            capture("ipad-landscape-editor")
            XCUIDevice.shared.orientation = .portrait
        }
    }
    /// 保存配置产生真实待提交项；未配服务器时同步明确提示，保存连接后重启保留账户和队列。
    @MainActor func testSyncQueueAndConnectionSettingsSurviveRestart() {
        launchCleanApp()
        selectTab("计算")
        reveal(app.buttons["save-configuration"]); app.buttons["save-configuration"].tap()
        reveal(app.staticTexts["configuration-save-status"])
        XCTAssertTrue(app.staticTexts["configuration-save-status"].waitForExistence(timeout: 10))
        configurationsRoot(); metric("open-synchronization").tap()
        XCTAssertEqual(metric("sync-pending-count").value as? String, "1")
        app.buttons["synchronize-now"].tap()
        XCTAssertTrue(app.alerts.staticTexts["请先在设置中保存服务器地址和同步账户。"].waitForExistence(timeout: 10))
        app.alerts.buttons["好"].tap()
        XCTAssertEqual(metric("sync-pending-count").value as? String, "1")
        selectTab("设置")
        let address = app.textFields["server-address"], identity = app.textFields["sync-user"]
        address.tap(); address.typeText("http://127.0.0.1:41106")
        identity.tap(); identity.typeText("ci-shared-user\n")
        reveal(app.buttons["save-server"]); app.buttons["save-server"].tap()
        reveal(app.staticTexts["settings-save-status"])
        XCTAssertTrue(app.staticTexts["settings-save-status"].waitForExistence(timeout: 10))
        app.terminate(); app.launchArguments = ["--ui-testing"]; app.launch()
        selectTab("设置")
        XCTAssertEqual(app.textFields["server-address"].value as? String, "http://127.0.0.1:41106")
        XCTAssertEqual(app.textFields["sync-user"].value as? String, "ci-shared-user")
        selectTab("配置"); metric("open-synchronization").tap()
        XCTAssertEqual(metric("sync-pending-count").value as? String, "1")
        capture("sync-queue-after-restart")
    }
    /// 知识来源必须由用户保存并跨重启恢复；保存不会自动访问填写的回环服务。
    @MainActor func testKnowledgeUpdateSourceSurvivesRestart() {
        launchCleanApp()
        selectTab("设置")
        reveal(metric("open-knowledge-update")); metric("open-knowledge-update").tap()
        let address = app.textFields["knowledge-manifest-url"]
        XCTAssertTrue(address.waitForExistence(timeout: 10)); address.tap()
        address.typeText("http://127.0.0.1:41107/packs/manifest.json\n")
        app.buttons["save-knowledge-source"].tap()
        reveal(app.staticTexts["knowledge-update-status"])
        XCTAssertEqual(app.staticTexts["knowledge-update-status"].label, "知识来源已保存")
        XCTAssertTrue(app.buttons["download-knowledge-update"].exists)
        XCTAssertFalse(app.buttons["cancel-knowledge-update"].exists)
        app.terminate(); app.launchArguments = ["--ui-testing"]; app.launch()
        selectTab("设置")
        reveal(metric("open-knowledge-update")); metric("open-knowledge-update").tap()
        XCTAssertEqual(app.textFields["knowledge-manifest-url"].value as? String, "http://127.0.0.1:41107/packs/manifest.json")
        capture("knowledge-update-source-after-restart")
    }
    /// 实际App保存动态Go地址并调用正式Core子进程；来源/精确结果/三个版本均来自真实完成响应。
    @MainActor func testLiveGoOnlineCalculationMatchesOffline() throws {
        let services = try liveServices()
        launchCleanApp(); configureLiveConnection(services)
        selectTab("计算")
        reveal(app.buttons["calculate-offline"]); app.buttons["calculate-offline"].tap()
        reveal(metric("calculation-source")); waitForValue(metric("calculation-source"), value: "本机离线")
        reveal(metric("damage-range"))
        XCTAssertEqual(metric("damage-range").value as? String, "99–117")
        reveal(metric("two-hit-probability"))
        XCTAssertEqual(metric("two-hit-probability").value as? String, "123/128")
        reveal(app.buttons["calculate-online"], upward: false)
        capture("online-calculation-button-visible"); app.buttons["calculate-online"].tap()
        reveal(metric("calculation-source"))
        let origin = "服务器 \(services.serverURL.host ?? "")\(services.serverURL.port.map { ":\($0)" } ?? "")"
        waitForValue(metric("calculation-source"), value: origin)
        reveal(metric("damage-range"))
        XCTAssertEqual(metric("damage-range").value as? String, "99–117")
        reveal(metric("two-hit-probability"))
        XCTAssertEqual(metric("two-hit-probability").value as? String, "123/128")
        reveal(metric("calculation-engine-version")); XCTAssertEqual(metric("calculation-engine-version").value as? String, services.engineVersion)
        reveal(metric("calculation-rules-version")); XCTAssertEqual(metric("calculation-rules-version").value as? String, services.rulesVersion)
        reveal(metric("calculation-knowledge-version")); XCTAssertEqual(metric("calculation-knowledge-version").value as? String, services.knowledgeVersion)
        XCTAssertFalse(app.alerts.firstMatch.exists)
        capture("live-go-online-calculation")
    }

    /// 真实App→Go→独立PG；iPad先拉取iPhone已提交配置，再各自保存/同步/重启恢复，不能用内存队列替代。
    @MainActor func testLiveGoSyncBetweenPhoneAndPadAndRestart() throws {
        let services = try liveServices()
        launchCleanApp(); configureLiveConnection(services)
        selectTab("配置"); metric("open-synchronization").tap()
        app.buttons["synchronize-now"].tap()
        reveal(app.staticTexts["synchronization-status"])
        XCTAssertTrue(app.staticTexts["synchronization-status"].waitForExistence(timeout: 20))
        waitForValue(metric("sync-pending-count"), value: "0")
        configurationsRoot()
        if UIDevice.current.userInterfaceIdiom == .pad {
            let pulled = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "saved-configuration-")).firstMatch
            XCTAssertTrue(pulled.waitForExistence(timeout: 15), "iPad must pull the configuration previously uploaded by the real iPhone App")
            capture("ipad-pulled-iphone-configuration")
        }
        selectTab("计算"); reveal(app.buttons["save-configuration"]); app.buttons["save-configuration"].tap()
        reveal(app.staticTexts["configuration-save-status"])
        XCTAssertTrue(app.staticTexts["configuration-save-status"].waitForExistence(timeout: 10))
        configurationsRoot(); metric("open-synchronization").tap()
        waitForValue(metric("sync-pending-count"), value: "1")
        app.buttons["synchronize-now"].tap(); waitForValue(metric("sync-pending-count"), value: "0")
        XCTAssertTrue(app.staticTexts["synchronization-status"].waitForExistence(timeout: 20))
        XCTAssertFalse(app.alerts.firstMatch.exists)
        capture("live-go-sync-uploaded")
        app.terminate(); app.launchArguments = ["--ui-testing"]; app.launch()
        configurationsRoot(); metric("open-synchronization").tap()
        waitForValue(metric("sync-pending-count"), value: "0")
        app.buttons["synchronize-now"].tap()
        XCTAssertTrue(app.staticTexts["synchronization-status"].waitForExistence(timeout: 20))
        XCTAssertFalse(app.alerts.firstMatch.exists)
        capture("live-go-sync-after-restart")
    }

    /// 实际App通过原POST合同提交默认单配置对，观察正式daemon终态和完整精确结果，不提交CoreJSON演示。
    @MainActor func testLiveGoTaskSubmissionAndExactResult() throws {
        let services = try liveServices()
        launchCleanApp(); configureLiveConnection(services)
        configurationsRoot(); metric("open-configuration-jobs").tap()
        reveal(app.buttons["submit-configuration-job"]); app.buttons["submit-configuration-job"].tap()
        reveal(metric("configuration-job-id"), upward: false)
        XCTAssertTrue(metric("configuration-job-id").waitForExistence(timeout: 20), "Original job API must return a real job ID")
        XCTAssertFalse(metric("configuration-job-id").label.isEmpty)
        reveal(metric("configuration-job-phase")); waitForValue(metric("configuration-job-phase"), value: "已完成", timeout: 60)
        capture("live-go-task-completed")
        let result = metric("configuration-job-case-0")
        reveal(result); XCTAssertTrue(result.waitForExistence(timeout: 10)); result.tap()
        waitForValue(metric("job-result-attacker-win"), value: "0")
        XCTAssertEqual(metric("job-result-defender-win").value as? String, "1")
        XCTAssertEqual(metric("job-result-draw").value as? String, "0")
        XCTAssertEqual(metric("job-result-expected-turns").value as? String, "5/1")
        reveal(metric("job-result-engine")); waitForValue(metric("job-result-engine"), value: services.engineVersion)
        reveal(metric("job-result-rules")); waitForValue(metric("job-result-rules"), value: services.rulesVersion)
        XCTAssertFalse(app.alerts.firstMatch.exists)
        capture("live-go-task-exact-result")
    }

    /// 使用正式Go已验证的75case候选池留出真实取消窗口；只在UI填入合法命令，不注入延迟或演示结果。
    @MainActor func testLiveGoTaskCancellation() throws {
        let services = try liveServices()
        launchCleanApp(); configureLiveConnection(services)
        configurationsRoot(); metric("open-configuration-jobs").tap()
        let moves = app.textFields["job-attacker-moves"]
        appendMoveIDs([17, 806, 814, 851], to: moves, startingValue: "404")
        XCTAssertEqual(moves.value as? String, "404,17,806,814,851")
        let defender = app.textFields["job-defender-moves"]
        appendMoveIDs([17, 21, 56, 401, 406], to: defender, startingValue: "337")
        XCTAssertEqual(defender.value as? String, "337,17,21,56,401,406")
        reveal(app.buttons["submit-configuration-job"]); app.buttons["submit-configuration-job"].tap()
        let cancel = app.buttons["cancel-configuration-job"]
        reveal(cancel, upward: false)
        XCTAssertTrue(cancel.waitForExistence(timeout: 20), "A real submitted task must expose server cancellation")
        cancel.tap()
        reveal(metric("configuration-job-phase"), upward: false)
        waitForValue(metric("configuration-job-phase"), value: "已取消", timeout: 60)
        XCTAssertFalse(app.alerts.firstMatch.exists)
        capture("live-go-task-cancelled")
    }

    /// 在真实键盘逐项追加完整招式；每项实际值到达后才继续，保持原75case候选池不变。
    /// identifiers为依原顺序追加的正式ID；field为实际招式输入框；startingValue为表单原默认值。
    /// 本方法只进行UI输入和严格断言，不注入模型、缩短输入或用延迟制造取消窗口。
    @MainActor private func appendMoveIDs(_ identifiers: [Int], to field: XCUIElement, startingValue: String) {
        reveal(field); field.tap()
        waitForValue(field, value: startingValue)
        var expected = startingValue
        for identifier in identifiers {
            let addition = ",\(identifier)"
            field.typeText(addition)
            expected += addition
            // iPad长串typeText曾只留下前缀；每个完整ID都必须真实出现在控件中。
            waitForValue(field, value: expected)
        }
        field.typeText("\n")
        waitForValue(field, value: expected)
    }

    /// 测试资源由验收脚本通过真实回环Go/PG环境生成；缺失即失败，不能把实际网络验收静默跳过。
    @MainActor private func liveServices() throws -> LiveServices {
        let url = try XCTUnwrap(Bundle(for: PokemonAppUITests.self).url(forResource: "online-services", withExtension: "json"), "Run validate-apple-app.sh to supply real Go and PostgreSQL services")
        return try JSONDecoder().decode(LiveServices.self, from: Data(contentsOf: url))
    }
    /// services包含本轮自有服务和同步账户；通过实际设置控件写入SQLite，不注入App内部网络状态。
    @MainActor private func configureLiveConnection(_ services: LiveServices) {
        selectTab("设置")
        let address = app.textFields["server-address"], identity = app.textFields["sync-user"]
        address.tap(); address.typeText(services.serverURL.absoluteString)
        identity.tap(); identity.typeText(services.syncUser + "\n")
        reveal(app.buttons["save-server"]); app.buttons["save-server"].tap()
        reveal(app.staticTexts["settings-save-status"])
        XCTAssertTrue(app.staticTexts["settings-save-status"].waitForExistence(timeout: 10))
    }
    /// name 为四个公开入口的中文名称；iPhone 底部TabBar和iPad顶部浮动按钮都保留相同可见标签。
    @MainActor private func tab(_ name: String) -> XCUIElement { app.buttons.matching(NSPredicate(format: "label == %@", name)).firstMatch }
    /// name 为实际入口名称；点击真实可见按钮，不通过 launch 参数或内部状态跳过业务导航。
    @MainActor private func selectTab(_ name: String) {
        let button = tab(name)
        XCTAssertTrue(button.waitForExistence(timeout: 30), "Application navigation entry must exist")
        button.tap()
    }
    /// Tab切换保留NavigationStack；实际点返回按钮回配置列表，不能假设重选tab会自动回根页面。
    @MainActor private func configurationsRoot() {
        selectTab("配置")
        if !metric("open-synchronization").waitForExistence(timeout: 2) {
            let back = app.navigationBars.buttons.firstMatch
            XCTAssertTrue(back.exists && back.isHittable, "Configuration detail must provide a real back button")
            back.tap()
        }
        XCTAssertTrue(metric("open-synchronization").waitForExistence(timeout: 10), "Configuration root must appear")
    }
    /// element 为真实开关或结果行，value 为严格预期值；timeout为异步操作的等待秒数，不接受其他值。
    @MainActor private func waitForValue(_ element: XCUIElement, value: String, timeout: TimeInterval = 15) {
        let expected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", value), object: element)
        let status = XCTWaiter.wait(for: [expected], timeout: timeout)
        if status != .completed { capture("unexpected-control-value") }
        XCTAssertEqual(status, .completed, "Actual accessibility value must match the expected value")
        XCTAssertEqual(element.value as? String, value)
    }
    /// identifier 对应显式 accessibilityValue 指标；按稳定语义定位，不依赖 LabeledContent 合并类型。
    @MainActor private func metric(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any)[identifier].firstMatch
    }
    /// element 是当前页真实控件；upward 为尚未进入可查询范围时的滚动方向。
    /// 有限次实际滚动至完整控件位于NavBar/TabBar之间；isHittable单独可能误报被顶栏遮挡的Form按钮。
    @MainActor private func reveal(_ element: XCUIElement, upward: Bool = true) {
        for _ in 0..<12 {
            _ = element.waitForExistence(timeout: 0.5)
            if element.exists {
                let frame = element.frame, screen = app.frame
                var top = screen.minY, bottom = screen.maxY
                // 从实际横向覆盖该控件的导航/标签栏计算边界，兼容iPad顶部标签栏及iPhone底栏。
                for bar in app.navigationBars.allElementsBoundByIndex + app.tabBars.allElementsBoundByIndex where bar.exists {
                    let overlay = bar.frame
                    guard overlay.minX <= frame.midX, frame.midX <= overlay.maxX else { continue }
                    if overlay.maxY <= screen.midY { top = max(top, overlay.maxY) }
                    else if overlay.minY >= screen.midY { bottom = min(bottom, overlay.minY) }
                }
                if frame.minY < top + 4 { app.swipeDown(); continue }
                if frame.maxY > bottom - 4 { app.swipeUp(); continue }
                if element.isHittable { return }
            }
            if upward { app.swipeUp() } else { app.swipeDown() }
        }
    }
    /// name 是 xcresult 附件名；保留屏幕图用于独立审查 phone/pad 的真实布局。
    @MainActor private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.name = name; attachment.lifetime = .keepAlways
        add(attachment)
        let hierarchy = XCTAttachment(string: app.debugDescription); hierarchy.name = "\(name)-hierarchy"; hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }
}

/// 仅测试bundle持有的本轮动态回环环境与实际Core探测版本，不进入App产品或生产配置。
private struct LiveServices: Decodable {
    let serverURL: URL
    let syncUser: String
    let engineVersion: String
    let rulesVersion: String
    let knowledgeVersion: String
}
