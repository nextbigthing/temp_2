from PyQt5.QtCore import *
from kiwoom import Kiwoom
from PyQt5.QtWidgets import *
from PyQt5.QtTest import *


class Thread4(QThread):
    """자동매매를 담당하는 Thread"""

     # 시그널 정의
    update_status = pyqtSignal(str)
    trade_done = pyqtSignal(dict)

    def __init__(self, parent):
         super().__init__(parent)
         self.parent = parent

        # 키움 인스턴스
         self.k = Kiwoom()

        # 자동매매 관련 변수
         self.is_running = False
         self.buy_list = []  # 매수할 종목 리스트
         self.buy_amount = 0  # 종목당 매수 금액
         self.profit_rate = 0  # 목표 수익률
         self.account_num = ""  # 계좌번호
         self.bought_stocks = {}  # 매수한 종목 저장

        # 스크린번호
         self.buy_screen = "4001"  # 매수용 스크린
         self.sell_screen = "4002"  # 매도용 스크린
         self.acc_screen = "4003"  # 계좌조회용 스크린
         self.price_screen = "4004"  # 현재가조회용 스크린

        # 이벤트 루프
         #self.price_event_loop = QEventLoop()
         #self.current_price_result = 0

        # 슬롯 연결
         try:
             self.k.kiwoom.OnReceiveTrData.connect(self.trdata_slot)
             self.k.kiwoom.OnReceiveChejanData.connect(self.chejan_slot)
         except Exception as e:
             print(f"슬롯 연결 오류: {e}")


    def run(self):
        """Thread 실행"""
        try:
            print("========== 자동매매 시작 ==========")
            self.is_running = True

            # 1. 매수할 종목 리스트 가져오기
            self.get_buy_list()

            if len(self.buy_list) == 0:
                self.update_status.emit("매수할 종목이 없습니다.")
                return

            # 2. 종목당 매수 금액 설정
            self.buy_amount = int(self.parent.buy_price.value())
            stock_count = len(self.buy_list)
            total_investment = self.buy_amount * stock_count

            self.profit_rate = self.parent.profit_percent.value()
            self.account_num = self.parent.redaccComboBox.currentText()

            print(f"계좌번호: {self.account_num}")
            print(f"매수 종목 수: {stock_count}")
            print(f"종목당 매수금액: {self.buy_amount:,}원")
            print(f"총 투자금액: {total_investment:,}원")
            print(f"목표 수익률: {self.profit_rate}%")

            # 3. 현재가 조회 후 매수 실행

            self.execute_buy_orders_with_price()

            # 4. 매수 후 잠시 대기
            print("\n매수 주문 완료. 10초 후 모니터링 시작...")
            QTest.qWait(10000)  # 10초 대기

            # 5. 자체 모니터링 및 매도
            self.self_monitor_and_sell()

        except Exception as e:
            print(f"자동매매 Thread 오류: {e}")
            import traceback
            traceback.print_exc()
            self.update_status.emit(f"자동매매 오류: {str(e)}")


    def get_buy_list(self):
        """buylists 테이블에서 매수할 종목 정보 가져오기"""
        self.buy_list = []

        for row in range(self.parent.buylists.rowCount()):
            code_item = self.parent.buylists.item(row, 0)
            name_item = self.parent.buylists.item(row, 1)
            price_item = self.parent.buylists.item(row, 2)  # 가격 정보도 가져오기

            if code_item and name_item:
                code = code_item.text()
                name = name_item.text()

                # 가격 파싱
                price = 0
                if price_item:
                    price_text = price_item.text().replace(",", "")
                    try:
                        price = int(price_text)
                    except:
                        price = 0

                self.buy_list.append({
                    "종목코드": code,
                    "종목명": name,
                    "현재가": price  # 가격 추가
                })

                self.bought_stocks[code] = {
                    "종목명": name,
                    "매수완료": False
                }

        print(f"매수 대상 종목: {self.buy_list}")


    def get_current_price(self, code):
        """종목의 현재가 조회 (간단 버전)"""
        try:
            print(f"  현재가 조회 중: {code}")

            self.k.kiwoom.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
            ret = self.k.kiwoom.dynamicCall("CommRqData(QString, QString, int, QString)",
                                            "주식기본정보", "opt10001", 0, self.price_screen)

            if ret == 0:
                self.price_event_loop.exec_()  # 응답 대기
                return abs(self.current_price_result) if self.current_price_result else 0
            else:
                print(f"  현재가 조회 실패")
                return 0

        except Exception as e:
            print(f"  현재가 조회 오류: {e}")
            return 0

    def execute_buy_orders_with_price(self):
         """지정가로 정확한 금액 매수"""

         for stock in self.buy_list:
            if not self.is_running:
                break

            code = stock["종목코드"]
            name = stock["종목명"]

            print(f"\n매수 처리: {code} {name}")
            print(f"  목표 매수금액: {self.buy_amount:,}원")

            try:
                # 상한가 조회
                upper_limit = self.k.kiwoom.dynamicCall("GetMasterLastPrice(QString)", code)
                if not upper_limit or upper_limit == "":
                    upper_limit = 100000  # 기본값
                else:
                    upper_limit = abs(int(upper_limit))
                    # 상한가보다 약간 높게 설정 (즉시 체결 유도)
                    upper_limit = int(upper_limit * 1.05)

                print(f"  지정가: {upper_limit:,}원")

                # 금액 기준 수량 계산
                quantity = int(self.buy_amount / upper_limit)
                quantity = max(1, quantity)

                print(f"  매수 수량: {quantity}주")
                print(f"  최대 금액: {quantity * upper_limit:,}원")

                # 지정가 매수 (시장가보다 높게 설정하여 즉시 체결)
                order_result = self.k.kiwoom.dynamicCall(
                    "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                    ["매수주문", self.buy_screen, self.account_num, 1, code, quantity, upper_limit, "00", ""]
                    # "00": 지정가 주문
                )

                if order_result == 0:
                    self.update_status.emit(f"{name} {quantity}주 주문")
                    print(f"  >>> 주문 성공")
                else:
                    print(f"  >>> 주문 실패: {order_result}")

            except Exception as e:
                print(f"  오류: {e}")

            QTest.qWait(1000)

    def self_monitor_and_sell(self):
        """자체적으로 계좌 조회하며 익절 감시"""
        print("\n========== 자체 모니터링 시작 ==========")

        monitor_count = 0
        while self.is_running:
            monitor_count += 1
            print(f"\n--- 모니터링 #{monitor_count} ---")

            try:
                # 계좌평가잔고 조회
                self.request_account_evaluation()

                # 보유종목 확인 및 익절 처리
                self.check_and_sell_positions()

                # 모든 종목이 매도되었는지 확인
                if len(self.bought_stocks) == 0:
                    print("모든 종목 매도 완료. 자동매매 종료")
                    break

            except Exception as e:
                print(f"모니터링 오류: {e}")

            # 30초 간격으로 체크
            print("30초 후 다시 체크...")
            for i in range(30):
                if not self.is_running:
                    break
                QTest.qWait(1000)


    def self_monitor_and_sell(self):
        """자체적으로 계좌 조회하며 익절 감시"""
        print("\n========== 자체 모니터링 시작 ==========")

        monitor_count = 0
        while self.is_running:
            monitor_count += 1
            print(f"\n--- 모니터링 #{monitor_count} ---")

            try:
                # 계좌평가잔고 조회
                self.request_account_evaluation()

                # 보유종목 확인 및 익절 처리
                self.check_and_sell_positions()

                # 모든 종목이 매도되었는지 확인
                if len(self.bought_stocks) == 0:
                    print("모든 종목 매도 완료. 자동매매 종료")
                    break

            except Exception as e:
                print(f"모니터링 오류: {e}")

            # 30초 간격으로 체크
            print("30초 후 다시 체크...")
            for i in range(30):
                if not self.is_running:
                    break
                QTest.qWait(1000)


    def request_account_evaluation(self):
        """계좌평가잔고 조회"""
        try:
            print("계좌 정보 조회 중...")

            # 계좌평가잔고내역 요청
            self.k.kiwoom.dynamicCall("SetInputValue(String, String)", "계좌번호", self.account_num)
            self.k.kiwoom.dynamicCall("SetInputValue(String, String)", "비밀번호", "0000")
            self.k.kiwoom.dynamicCall("SetInputValue(String, String)", "비밀번호입력매체구분", "00")
            self.k.kiwoom.dynamicCall("SetInputValue(String, String)", "조회구분", "2")

            ret = self.k.kiwoom.dynamicCall("CommRqData(String, String, int, String)",
                                            "계좌평가", "opw00018", 0, self.acc_screen)

            if ret == 0:
                print("계좌 조회 요청 성공")
                QTest.qWait(2000)  # 2초 대기
            else:
                print(f"계좌 조회 요청 실패: {ret}")

        except Exception as e:
            print(f"계좌 조회 오류: {e}")


    def check_and_sell_positions(self):
        """보유종목 확인 및 익절 매도"""
        try:
            # k.acc_portfolio에서 보유종목 정보 확인
            if not hasattr(self.k, 'acc_portfolio') or not self.k.acc_portfolio:
                print("보유종목 정보 없음")
                return

            print(f"보유종목 수: {len(self.k.acc_portfolio)}")

            for code, info in self.k.acc_portfolio.items():
                # 매수한 종목인지 확인
                if code not in self.bought_stocks:
                    continue

                name = info.get("종목명", "")
                current_rate = info.get("수익률(%)", 0)
                quantity = info.get("보유수량", 0)
                current_price = info.get("현재가", 0)

                print(f"  {code} {name}: 수익률 {current_rate:.2f}%, 현재가 {current_price:,}원")

                # 목표 수익률 도달 확인
                if current_rate >= self.profit_rate and quantity > 0:
                    print(f"  >>> 익절 조건 달성! 매도 주문 실행")

                    # 시장가 매도 주문
                    order_result = self.k.kiwoom.dynamicCall(
                        "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                        ["매도주문", self.sell_screen, self.account_num, 2, code, quantity, 0, "03", ""]
                    )

                    if order_result == 0:
                        self.update_status.emit(f"{name} 익절 매도 주문 ({current_rate:.2f}%)")
                        self.trade_done.emit({
                            "종목코드": code,
                            "종목명": name,
                            "수익률": current_rate,
                            "매매구분": "매도"
                        })
                        print(f"  매도 주문 성공")

                        # 매도한 종목은 목록에서 제거
                        del self.bought_stocks[code]
                    else:
                        self.update_status.emit(f"{name} 매도 실패")
                        print(f"  매도 주문 실패: {order_result}")

        except Exception as e:
            print(f"익절 처리 오류: {e}")


    def stop(self):
        """자동매매 중지"""
        self.is_running = False
        self.update_status.emit("자동매매가 중지되었습니다.")
        print("========== 자동매매 종료 ==========")


    def trdata_slot(self, sScrNo, sRQName, sTrCode, sRecordName, sPrevNext):
        """TR 데이터 수신"""
        try:
            # # 현재가 조회 응답
            # if sRQName == "주식기본정보":
            #     current_price = self.k.kiwoom.dynamicCall(
            #         "GetCommData(QString, QString, int, QString)",
            #         sTrCode, sRQName, 0, "현재가"
            #     ).strip()
            #
            #     self.current_price_result = int(current_price.replace("+", "").replace("-", ""))
            #     print(f"    현재가 수신: {self.current_price_result:,}원")
            #
            #     if hasattr(self, 'price_event_loop') and self.price_event_loop:
            #         self.price_event_loop.exit()

            # 계좌평가 응답
            if sRQName == "계좌평가" and sTrCode == "opw00018":
                cnt = self.k.kiwoom.dynamicCall("GetRepeatCnt(QString, QString)", sTrCode, sRQName)
                print(f"TR 수신: 보유종목 {cnt}개")

                for i in range(cnt):
                    code = self.k.kiwoom.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        sTrCode, sRQName, i, "종목번호"
                    ).strip().replace("A", "")

                    if code:
                        name = self.k.kiwoom.dynamicCall(
                            "GetCommData(QString, QString, int, QString)",
                            sTrCode, sRQName, i, "종목명"
                        ).strip()

                        quantity = int(self.k.kiwoom.dynamicCall(
                            "GetCommData(QString, QString, int, QString)",
                            sTrCode, sRQName, i, "보유수량"
                        ).strip())

                        buy_price = abs(int(self.k.kiwoom.dynamicCall(
                            "GetCommData(QString, QString, int, QString)",
                            sTrCode, sRQName, i, "매입가"
                        ).strip()))

                        current_price = abs(int(self.k.kiwoom.dynamicCall(
                            "GetCommData(QString, QString, int, QString)",
                            sTrCode, sRQName, i, "현재가"
                        ).strip()))

                        profit_rate = float(self.k.kiwoom.dynamicCall(
                            "GetCommData(QString, QString, int, QString)",
                            sTrCode, sRQName, i, "수익률(%)"
                        ).strip())

                        # 싱글톤 딕셔너리 업데이트
                        if code not in self.k.acc_portfolio:
                            self.k.acc_portfolio[code] = {}

                        self.k.acc_portfolio[code].update({
                            "종목명": name,
                            "보유수량": quantity,
                            "매입가": buy_price,
                            "현재가": current_price,
                            "수익률(%)": profit_rate
                        })

                print("계좌 정보 업데이트 완료")

        except Exception as e:
            print(f"TR 데이터 처리 오류: {e}")

    def chejan_slot(self, sGubun, nItemCnt, sFIdList):
        """체결 데이터 수신"""
        try:
            if sGubun == "0":  # 주문 체결
                order_status = self.k.kiwoom.dynamicCall("GetChejanData(int)", 913).strip()
                code = self.k.kiwoom.dynamicCall("GetChejanData(int)", 9001).strip().replace("A", "")
                name = self.k.kiwoom.dynamicCall("GetChejanData(int)", 302).strip()
                order_quantity = self.k.kiwoom.dynamicCall("GetChejanData(int)", 900).strip()
                executed_quantity = self.k.kiwoom.dynamicCall("GetChejanData(int)", 911).strip()
                price = self.k.kiwoom.dynamicCall("GetChejanData(int)", 910).strip()

                print(f"\n>>> 체결 알림 <<<")
                print(f"  종목: {code} {name}")
                print(f"  주문상태: {order_status}")
                print(f"  체결수량: {executed_quantity}주")
                print(f"  체결가: {price}원")

                # 체결 금액 계산
                if executed_quantity and price:
                    total_amount = int(executed_quantity) * int(price)
                    print(f"  체결금액: {total_amount:,}원")

                    # 목표 금액과 비교
                    if code in self.bought_stocks:
                        target_amount = self.bought_stocks[code].get("목표금액", 0)
                        if target_amount > 0:
                            diff = total_amount - target_amount
                            if diff > 0:
                                print(f"  ⚠️ 목표금액 {target_amount:,}원 초과: +{diff:,}원")
                            else:
                                print(f"  ✓ 목표금액 {target_amount:,}원 내 체결")

                if order_status == "체결":
                    self.update_status.emit(f"{name} 체결 완료 ({executed_quantity}주 × {price}원)")

        except Exception as e:
            print(f"체결 데이터 처리 오류: {e}")