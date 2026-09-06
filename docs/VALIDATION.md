# 验证边界

运行 scripts/validate_project.py、tests/compact 和保留的旧 tests。版本交付需重新解压
源码包复验，检查文件集合/字节一致性，不生成额外 hash。

确定性宿主替身只验证控制协议、并发和状态流转。测试里的 PDF 生成替身验证发布和
PDF inspector，不证明 Marp/DOM 或真实模型质量。生产不提供跳过/替换 gate 的配置。
部署必须显式安装固定 toolchain，并运行 mpres toolchain doctor 与真实小稿流程。
Windows 启动脚本须在 Windows 原生环境补验。失败、未运行和真实通过应分开记录。
