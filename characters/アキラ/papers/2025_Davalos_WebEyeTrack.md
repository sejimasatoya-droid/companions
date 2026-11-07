# WebEyeTrack: Scalable Eye-Tracking for the Browser via On-Device Few-Shot Personalization

- 著者：Eduardo Davalos, Yike Zhang, Namrata Srivastava, Yashvitha Thatigotla, Jorge A. Salas, Sara McFadden, Sun-Joo Cho, Amanda Goodwin, Ashwin T S, Gautam Biswas
- 年：2025
- 掲載誌・会議：arXiv 2508.19544（AAAI の書式）
- DOI / URL：https://arxiv.org/abs/2508.19544 ／ コード：https://github.com/RedForestAI/WebEyeTrack
- 原文の場所：pdfs/2025_Davalos_WebEyeTrack.pdf（手元にのみ保存）
- キーワード：ウェブカメラ視線計測, ブラウザ, 軽量モデル, 少数ショット学習, メタ学習, 頭部姿勢推定, プライバシー

## 問い
- 最新の視線推定モデルは精度は高いが、モデルの大きさ・推論時間・プライバシーの問題で実用されにくい。ブラウザの中だけで、軽くて精度の良い視線計測はできるか？

## 方法
- 軽量な視線推定モデル（BlazeGaze）をブラウザの中で動かす
- モデルに基づく頭部姿勢の推定と、9点以下のキャリブレーションでの端末上の少数ショット学習で、新しい利用者に適応させる

## 結果
- GazeCapture データセットで誤差 2.32cm（最先端並み）
- iPhone 14 で推論 2.4ms のリアルタイム動作
- 利用者や時間をまたいでも頑健
- 今後の課題：公平性の改善、消費電力の削減

## アキラの感想・疑問
- オンライン実験で視線が取れるようになると、Sasmita & Swallow (2022) みたいなオンライン分節研究と組み合わせられるね
- 誤差が cm 単位で出てるけど、実験で使うなら視角の度に直して考えたい。画面までの距離が人によって違うから
- 端末上で処理が完結するのはプライバシーの点でいい。倫理審査の説明もしやすそう

## 瀬島君と話したこと
<!--
### YYYY-MM-DD
- 
-->
