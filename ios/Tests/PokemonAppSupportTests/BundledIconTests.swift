import Foundation
import XCTest
@testable import PokemonAppSupport

/// 只读检查真实随包的全图鉴图标；不依赖网络、UIKit或NAS，Apple和Linux使用同一断言。
final class BundledIconTests: XCTestCase, @unchecked Sendable {
    /// 图标清单边界，不复用图标生成器；只解码实际需要核对的固定字段。
    private struct Manifest: Decodable {
        let sourceCommit: String
        let game: String
        let assetCount: Int
        let byteSize: Int
        let assets: [Asset]
    }
    /// 实际文件的类别、身份、SHA和尺寸；来自打包清单，不能仅凭文件名认定图片完整。
    private struct Asset: Decodable {
        /// 三种固定资源类别，与实际清单的字符串一一对应。
        enum Kind: String, Decodable { case pokemon, item, type }
        let kind: Kind
        let identifier: String
        let resourceName: String
        let sha256: String
        let byteSize: Int
        let width: Int
        let height: Int
    }

    /// 首装必须捆绑默认计算、验收和朱紫御三家图标，未知编号及无道具明确返回nil。
    func testRequiredOfflineIdentitiesAndMissingIcons() throws {
        for id: Int64 in [25, 149, 212, 242, 700, 906, 909, 912, 1007, 1008] {
            XCTAssertNotNil(BundledIcons.url(for: .pokemon(id)), "Required Pokemon icon must be bundled")
        }
        for item in ItemRule.allCases where item != .none {
            XCTAssertNotNil(BundledIcons.url(for: .item(item)), "Current held-item icon must be bundled")
        }
        XCTAssertNotNil(BundledIcons.url(for: .elementType(9)))
        XCTAssertNil(BundledIcons.url(for: .pokemon(999999)))
        XCTAssertNil(BundledIcons.url(for: .pokemon(-1)))
        XCTAssertNil(BundledIcons.url(for: .item(.none)))
    }

    /// 核对全部1374份PNG的真实字节、SHA、尺寸和总包体，验证SPM按原字节复制而非重压图片。
    func testEveryBundledPNGMatchesSelectedManifest() throws {
        let first = try XCTUnwrap(BundledIcons.url(for: .pokemon(212)))
        let descriptor = first.deletingLastPathComponent().appendingPathComponent("icons-manifest.json")
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let manifest = try decoder.decode(Manifest.self, from: Data(contentsOf: descriptor))
        XCTAssertEqual(manifest.sourceCommit, "c0542f7c51215d9672439012838c99f520596cbd")
        XCTAssertEqual(manifest.game, "scarlet-violet")
        XCTAssertEqual(manifest.assetCount, 1374)
        XCTAssertEqual(manifest.byteSize, 20079618)
        XCTAssertEqual(manifest.assets.count, manifest.assetCount)
        XCTAssertEqual(manifest.assets.filter { $0.kind == .pokemon }.count, 1350)
        XCTAssertEqual(manifest.assets.filter { $0.kind == .item }.count, 5)
        XCTAssertEqual(manifest.assets.filter { $0.kind == .type }.count, 19)
        var total = 0
        for asset in manifest.assets {
            let icon: BundledIcon
            switch asset.kind {
            case .pokemon: icon = .pokemon(try XCTUnwrap(Int64(asset.identifier)))
            case .item:
                icon = .item(try XCTUnwrap(ItemRule(rawValue: asset.identifier.replacingOccurrences(of: "-", with: "_"))))
            case .type: icon = .elementType(try XCTUnwrap(Int64(asset.identifier)))
            }
            let file = try XCTUnwrap(BundledIcons.url(for: icon))
            XCTAssertEqual(file.deletingPathExtension().lastPathComponent, asset.resourceName)
            let bytes = try Data(contentsOf: file)
            XCTAssertEqual(bytes.count, asset.byteSize)
            XCTAssertEqual(Array(bytes.prefix(8)), [137, 80, 78, 71, 13, 10, 26, 10])
            XCTAssertEqual(try FileChecksum.sha256(file), asset.sha256)
            // 上游菜单图按人物边界裁剪，尺寸并非统一128x128；逐项核对真实IHDR而非硬编码假设。
            let width = bytes[16..<20].reduce(0) { ($0 << 8) | Int($1) }
            let height = bytes[20..<24].reduce(0) { ($0 << 8) | Int($1) }
            XCTAssertEqual(width, asset.width); XCTAssertEqual(height, asset.height)
            total += bytes.count
        }
        XCTAssertEqual(total, manifest.byteSize)
    }
}
