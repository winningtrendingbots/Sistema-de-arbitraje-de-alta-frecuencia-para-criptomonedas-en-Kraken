import krakenex
import requests
import time
import json
import os
from datetime import datetime
import hashlib
import hmac
import base64
import urllib.parse

class KrakenArbitrageBot:
    def __init__(self):
        self.api_key = os.environ.get('KRAKEN_API_KEY')
        self.api_secret = os.environ.get('KRAKEN_API_SECRET')
        self.telegram_token = os.environ.get('TELEGRAM_TOKEN')
        self.telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        self.kraken = krakenex.API(key=self.api_key, secret=self.api_secret)
        
        # Configuración REALISTA para rentabilidad
        self.min_profit_threshold = 1.0  # 1.0% mínimo (después de 0.52% comisiones = 0.48% neto)
        self.min_spread_alert = 0.8  # Alertar spreads anormales >0.8%
        self.max_position_size = 25  # USD por operación
        self.max_daily_trades = 20  # Límite para versión gratuita de GitHub
        
        # Stats tracking
        self.opportunities_found = 0
        self.avg_spread = 0
        
        # MODO TRADING (⚠️ PELIGROSO - Desactivado por defecto)
        self.auto_trade_enabled = os.environ.get('AUTO_TRADE_ENABLED', 'false').lower() == 'true'
        self.min_spread_to_trade = 1.5  # Solo tradea si hay >1.5% neto (muy conservador)
        self.trading_pairs = [
            # === PRINCIPALES (Muy líquidos, spreads bajos 0.01-0.1%) ===
            'XBTUSD', 'ETHUSD', 'XBTEUR', 'ETHEUR',
            'XBTUSDT', 'ETHUSDT',
            
            # === ALTCOINS TOP 20 (Líquidos, spreads 0.2-0.8%) ===
            'SOLUSD', 'ADAUSD', 'DOTUSD', 'MATICUSD',
            'LINKUSD', 'UNIUSD', 'AVAXUSD', 'ATOMUSD',
            'XRPUSD', 'LTCUSD', 'ALGOUSD', 'XLMUSD',
            
            # === ALTCOINS MEDIOS (Menos líquidos, spreads 0.8-2%) ===
            'FETUSD',   # AI/ML (Fetch.ai)
            'RENDERUSD', # GPU/Rendering
            'GRTUSD',    # The Graph
            'INJUSD',    # Injective
            'AAVEUSD',   # DeFi
            'COMPUSD',   # DeFi
            'SNXUSD',    # Synthetix
            'MANAUSD',   # Metaverse
            'SANDUSD',   # Metaverse
            
            # === MEMECOINS (MUY volátiles, spreads 1-5%) ===
            'DOGEUSD',   # Dogecoin
            'SHIBUSD',   # Shiba Inu
            'BONKUSD',   # Bonk
            'PEPEUSD',   # Pepe
            
            # === ALTCOINS PEQUEÑOS (ALTA volatilidad, spreads 2-10%) ===
            'ENJUSD',    # Gaming
            '1INCHUSD',  # DEX Aggregator
            'CHZUSD',    # Chiliz
            'BATUSD',    # Basic Attention Token
            'ZRXUSD',    # 0x Protocol
            'KNCUSD',    # Kyber Network
        ]
        
    def send_telegram(self, message):
        """Envía notificación por Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"Error enviando Telegram: {e}")
    
    def get_server_time(self):
        """Obtiene tiempo del servidor Kraken"""
        response = self.kraken.query_public('Time')
        return response['result']['unixtime']
    
    def get_ticker(self, pair):
        """Obtiene precio actual de un par"""
        try:
            response = self.kraken.query_public('Ticker', {'pair': pair})
            if 'result' in response and pair in response['result']:
                data = response['result'][pair]
                return {
                    'bid': float(data['b'][0]),
                    'ask': float(data['a'][0]),
                    'last': float(data['c'][0])
                }
            return None
        except Exception as e:
            print(f"Error obteniendo ticker {pair}: {e}")
            return None
    
    def get_balance(self):
        """Obtiene balance de la cuenta"""
        try:
            response = self.kraken.query_private('Balance')
            if 'result' in response:
                return response['result']
            return {}
        except Exception as e:
            print(f"Error obteniendo balance: {e}")
            return {}
    
    def calculate_triangular_arbitrage(self):
        """Calcula oportunidades de arbitraje triangular"""
        opportunities = []
        
        # Ejemplo: BTC/USD -> ETH/BTC -> ETH/USD
        triangles = [
            ('XBTUSD', 'ETHXBT', 'ETHUSD'),
            ('XBTEUR', 'ETHXBT', 'ETHEUR'),
            ('XBTUSDT', 'ETHXBT', 'ETHUSDT'),
        ]
        
        for pair1, pair2, pair3 in triangles:
            try:
                ticker1 = self.get_ticker(pair1)
                ticker2 = self.get_ticker(pair2)
                ticker3 = self.get_ticker(pair3)
                
                if not all([ticker1, ticker2, ticker3]):
                    continue
                
                # Compra BTC/USD, vende por ETH, vende ETH/USD
                forward_rate = ticker1['ask'] * ticker2['bid'] * ticker3['bid']
                reverse_rate = 1.0
                
                profit_pct = ((reverse_rate / forward_rate) - 1) * 100
                
                if profit_pct > self.min_profit_threshold:
                    opportunities.append({
                        'type': 'triangular',
                        'path': f"{pair1} -> {pair2} -> {pair3}",
                        'profit_pct': profit_pct,
                        'timestamp': datetime.now().isoformat()
                    })
                    
            except Exception as e:
                print(f"Error calculando arbitraje: {e}")
                continue
        
        return opportunities
    
    def calculate_cross_exchange_arbitrage(self):
        """Detecta diferencias de precio en el mismo par"""
        opportunities = []
        
        for pair in self.trading_pairs:
            ticker = self.get_ticker(pair)
            if not ticker:
                continue
            
            # Calcular spread bid-ask
            spread_pct = ((ticker['ask'] - ticker['bid']) / ticker['bid']) * 100
            
            # Calcular ganancia neta después de comisiones
            gross_profit = spread_pct
            net_profit = gross_profit - 0.52  # Comisiones Kraken (0.26% x 2)
            
            # Solo alertar si es REALMENTE rentable
            if net_profit >= self.min_profit_threshold:
                self.opportunities_found += 1
                opportunities.append({
                    'type': 'spread_VIABLE',
                    'pair': pair,
                    'bid': ticker['bid'],
                    'ask': ticker['ask'],
                    'spread_pct': spread_pct,
                    'net_profit_pct': net_profit,
                    'estimated_profit_usd': (net_profit / 100) * self.max_position_size,
                    'timestamp': datetime.now().isoformat(),
                    'viability': '✅ RENTABLE' if net_profit > 0 else '⚠️ NO RENTABLE'
                })
            # Alertar spreads anormales aunque no sean rentables
            elif spread_pct > self.min_spread_alert:
                opportunities.append({
                    'type': 'spread_watch',
                    'pair': pair,
                    'bid': ticker['bid'],
                    'ask': ticker['ask'],
                    'spread_pct': spread_pct,
                    'net_profit_pct': net_profit,
                    'timestamp': datetime.now().isoformat(),
                    'viability': '⚠️ Spread alto pero NO rentable (comisiones)'
                })
        
        return opportunities
    
    def place_order(self, pair, order_type, volume, price=None):
        """Coloca una orden en Kraken"""
        try:
            params = {
                'pair': pair,
                'type': order_type,
                'ordertype': 'market' if price is None else 'limit',
                'volume': str(volume)
            }
            
            if price:
                params['price'] = str(price)
            
            response = self.kraken.query_private('AddOrder', params)
            
            if 'result' in response:
                return {
                    'success': True,
                    'txid': response['result'].get('txid', []),
                    'descr': response['result'].get('descr', {})
                }
            else:
                return {
                    'success': False,
                    'error': response.get('error', 'Unknown error')
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def execute_arbitrage(self, opportunity):
        """Ejecuta una operación de arbitraje"""
        viability = opportunity.get('viability', '')
        
        if 'VIABLE' in str(opportunity.get('type', '')):
            msg = f"🚨🚨 <b>¡OPORTUNIDAD RENTABLE!</b> 🚨🚨\n\n"
        else:
            msg = f"⚠️ <b>Spread Alto Detectado</b>\n\n"
        
        msg += f"Tipo: {opportunity['type']}\n"
        
        if opportunity['type'] == 'triangular':
            msg += f"Ruta: {opportunity['path']}\n"
            msg += f"Ganancia estimada: {opportunity['profit_pct']:.2f}%\n"
        elif 'spread' in opportunity['type']:
            msg += f"Par: {opportunity['pair']}\n"
            msg += f"Spread bruto: {opportunity['spread_pct']:.3f}%\n"
            
            if 'net_profit_pct' in opportunity:
                msg += f"Ganancia NETA: {opportunity['net_profit_pct']:.3f}%\n"
                msg += f"Estado: {opportunity['viability']}\n"
                
            if 'estimated_profit_usd' in opportunity:
                msg += f"\n💰 Con ${self.max_position_size}:\n"
                msg += f"Ganancia estimada: ${opportunity['estimated_profit_usd']:.2f}\n"
        
        msg += f"\n⏰ {opportunity['timestamp']}"
        
        self.send_telegram(msg)
        
        # TRADING AUTOMÁTICO (solo si está habilitado)
        if self.auto_trade_enabled and 'VIABLE' in str(opportunity.get('type', '')):
            net_profit = opportunity.get('net_profit_pct', 0)
            
            if net_profit >= self.min_spread_to_trade:
                return self.execute_trade(opportunity)
        
        return False
    
    def execute_trade(self, opportunity):
        """Ejecuta el trade real en Kraken"""
        try:
            pair = opportunity['pair']
            
            # Obtener precio actual
            ticker = self.get_ticker(pair)
            if not ticker:
                self.send_telegram(f"❌ No se pudo obtener precio para {pair}")
                return False
            
            # Calcular volumen a tradear
            price = ticker['ask']
            volume = self.max_position_size / price
            volume = round(volume, 8)  # Kraken usa 8 decimales
            
            # COMPRAR al ask
            self.send_telegram(f"🔄 Ejecutando BUY {volume} {pair} @ ${price:.2f}")
            buy_order = self.place_order(pair, 'buy', volume)
            
            if not buy_order.get('success'):
                self.send_telegram(f"❌ Error BUY: {buy_order.get('error')}")
                return False
            
            time.sleep(2)  # Esperar confirmación
            
            # VENDER al bid
            sell_price = ticker['bid']
            self.send_telegram(f"🔄 Ejecutando SELL {volume} {pair} @ ${sell_price:.2f}")
            sell_order = self.place_order(pair, 'sell', volume)
            
            if not sell_order.get('success'):
                self.send_telegram(f"❌ Error SELL: {sell_order.get('error')}\n⚠️ Tienes posición abierta!")
                return False
            
            # Calcular ganancia real
            profit = (sell_price - price) * volume
            self.send_telegram(f"✅ Trade completado!\nGanancia: ${profit:.2f}")
            
            return True
            
        except Exception as e:
            self.send_telegram(f"❌ Error ejecutando trade: {str(e)}")
            return False
    
    def run(self):
        """Ejecuta el ciclo principal del bot"""
        start_time = datetime.now()
        self.send_telegram(f"🤖 <b>Bot Iniciado</b>\n{start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        try:
            # Obtener balance inicial
            balance = self.get_balance()
            balance_msg = "💰 <b>Balance:</b>\n"
            for currency, amount in balance.items():
                if float(amount) > 0:
                    balance_msg += f"{currency}: {amount}\n"
            self.send_telegram(balance_msg)
            
            # Buscar oportunidades
            triangular_opps = self.calculate_triangular_arbitrage()
            spread_opps = self.calculate_cross_exchange_arbitrage()
            
            total_opps = len(triangular_opps) + len(spread_opps)
            viable_opps = len([o for o in spread_opps if 'VIABLE' in o.get('type', '')])
            
            # Ejecutar trades si está habilitado
            trades_executed = 0
            if self.auto_trade_enabled and viable_opps > 0:
                self.send_telegram(f"⚠️ <b>MODO AUTO-TRADE ACTIVADO</b>\nBuscando oportunidades para tradear...")
                
                for opp in spread_opps:
                    if 'VIABLE' in opp.get('type', '') and opp.get('net_profit_pct', 0) >= self.min_spread_to_trade:
                        if self.execute_arbitrage(opp):
                            trades_executed += 1
                            time.sleep(5)  # Esperar entre trades
            
            if total_opps == 0:
                self.send_telegram("✅ Análisis completado.\n\n❌ No se encontraron spreads >0.8%\n\nEsto es NORMAL. Los spreads rentables (>1%) son raros.")
            else:
                msg = f"📊 <b>Análisis Completado</b>\n\n"
                msg += f"Total oportunidades: {total_opps}\n"
                msg += f"🎯 RENTABLES (>1% neto): {viable_opps}\n"
                msg += f"⚠️ Spreads altos pero no rentables: {total_opps - viable_opps}\n\n"
                
                # Mostrar solo las RENTABLES primero
                viable_spread = [o for o in spread_opps if 'VIABLE' in o.get('type', '')]
                if viable_spread:
                    msg += "🚨 <b>OPORTUNIDADES RENTABLES:</b>\n\n"
                    for opp in viable_spread[:3]:
                        msg += f"✅ {opp['pair']}\n"
                        msg += f"Spread: {opp['spread_pct']:.3f}%\n"
                        msg += f"Neto: {opp['net_profit_pct']:.3f}%\n"
                        msg += f"Ganancia: ${opp['estimated_profit_usd']:.2f}\n\n"
                
                # Luego las no rentables
                watch_spread = [o for o in spread_opps if 'watch' in o.get('type', '')]
                if watch_spread and len(msg) < 3000:
                    msg += "⚠️ <b>Spreads altos (NO rentables):</b>\n\n"
                    for opp in watch_spread[:2]:
                        msg += f"📊 {opp['pair']}\n"
                        msg += f"Spread: {opp['spread_pct']:.3f}%\n"
                        msg += f"Neto: {opp['net_profit_pct']:.3f}%\n\n"
                
                self.send_telegram(msg)
            
            # Resumen final si hubo trades
            if self.auto_trade_enabled:
                final_balance = self.get_balance()
                summary = f"\n\n📊 <b>Resumen de Sesión</b>\n"
                summary += f"Trades ejecutados: {trades_executed}\n"
                summary += f"Modo: {'🔴 AUTO' if self.auto_trade_enabled else '🟢 SOLO ALERTAS'}"
                self.send_telegram(summary)
            
            # Guardar resultados
            results = {
                'timestamp': start_time.isoformat(),
                'triangular_opportunities': triangular_opps,
                'spread_opportunities': spread_opps,
                'balance': balance
            }
            
            with open('arbitrage_results.json', 'w') as f:
                json.dump(results, f, indent=2)
            
        except Exception as e:
            error_msg = f"❌ <b>Error:</b>\n{str(e)}"
            self.send_telegram(error_msg)
            raise
        
        finally:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            self.send_telegram(f"✅ Bot finalizado\nDuración: {duration:.2f}s")

if __name__ == "__main__":
    bot = KrakenArbitrageBot()
    bot.run()
