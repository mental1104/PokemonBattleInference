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
        XCTAssertTrue(app.tabBars.buttons["计算"].waitForExistence(timeout: 30), "Application must finish real knowledge installation")
    }
    /// 首装中文搜索命中 SQLite 的巨钳螳螂记录，进入详情核对真实属性。
    @MainActor func testFirstInstallChineseKnowledgeSearch() {
        launchCleanApp()
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 10), "Knowledge search must exist")
        search.tap(); search.typeText("巨钳螳螂")
        let row = app.buttons["pokemon-212"]
        // NavigationLink 在不同 iOS 版本可暴露为 button 或 other，使用任意类型标识定位。
        let item = row.exists ? row : app.descendants(matching: .any)["pokemon-212"].firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 10), "Bundled database must return Scizor")
        item.tap()
        XCTAssertTrue(app.staticTexts["scizor"].waitForExistence(timeout: 10), "Detail must read real identifier")
        capture("first-install-knowledge")
    }
    /// 默认输入通过真实 Core 返回共享向量；麻痹重算体现输入绑定确实进入引擎。
    @MainActor func testOfflineDamageExactKOAndParalysis() {
        launchCleanApp()
        app.tabBars.buttons["计算"].tap()
        reveal(app.buttons["calculate-offline"]); app.buttons["calculate-offline"].tap()
        let damage = app.staticTexts["damage-range"]
        reveal(damage)
        XCTAssertTrue(damage.waitForExistence(timeout: 15), "Native result must appear")
        XCTAssertEqual(damage.label, "99–117")
        XCTAssertEqual(app.staticTexts["two-hit-probability"].label, "123/128")
        XCTAssertEqual(app.staticTexts["attacker-speed"].label, "85")
        capture("offline-damage-exact-ko")
        let paralysis = app.switches["attacker-paralyzed"]
        reveal(paralysis, upward: false); paralysis.tap()
        reveal(app.buttons["calculate-offline"]); app.buttons["calculate-offline"].tap()
        reveal(app.staticTexts["attacker-speed"])
        XCTAssertTrue(app.staticTexts["attacker-speed"].waitForExistence(timeout: 15))
        XCTAssertEqual(app.staticTexts["attacker-speed"].label, "42")
        capture("paralysis-speed")
    }
    /// 修改名称后保存并杀进程重启，检查配置从 SQLite 恢复并能继续编辑。
    @MainActor func testSaveRestartAndEditConfiguration() {
        launchCleanApp()
        app.tabBars.buttons["计算"].tap()
        let name = app.textFields["configuration-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 10)); name.tap()
        // 使用屏幕上实际编辑后的完整名称验证重启，而不依赖键盘语言的 Select All 菜单。
        name.typeText(" CI saved configuration\n")
        let edited = name.value as? String ?? ""
        XCTAssertTrue(edited.contains("CI saved configuration"))
        app.swipeUp()
        reveal(app.buttons["save-configuration"]); app.buttons["save-configuration"].tap()
        XCTAssertTrue(app.staticTexts["configuration-save-status"].waitForExistence(timeout: 10))
        app.terminate(); app.launchArguments = ["--ui-testing"]; app.launch()
        XCTAssertTrue(app.tabBars.buttons["配置"].waitForExistence(timeout: 30)); app.tabBars.buttons["配置"].tap()
        let saved = app.buttons.containing(.staticText, identifier: edited).firstMatch
        XCTAssertTrue(saved.waitForExistence(timeout: 10), "Saved configuration must survive process restart")
        capture("saved-after-restart")
        saved.tap()
        XCTAssertEqual(app.textFields["configuration-name"].value as? String, edited)
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCUIDevice.shared.orientation = .landscapeLeft
            capture("ipad-landscape-editor")
            XCUIDevice.shared.orientation = .portrait
        }
    }
    /// element 是当前页真实控件；有限次滚动直到可交互，upward 为向页面底部滚动。
    @MainActor private func reveal(_ element: XCUIElement, upward: Bool = true) {
        for _ in 0..<12 {
            _ = element.waitForExistence(timeout: 0.5)
            if element.exists && element.isHittable { return }
            if upward { app.swipeUp() } else { app.swipeDown() }
        }
    }
    /// name 是 xcresult 附件名；保留屏幕图用于独立审查 phone/pad 的真实布局。
    @MainActor private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.name = name; attachment.lifetime = .keepAlways
        add(attachment)
    }
}
