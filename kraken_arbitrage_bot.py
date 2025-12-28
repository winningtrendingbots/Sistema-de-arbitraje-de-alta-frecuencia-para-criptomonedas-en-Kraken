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
        
        # Configuración adaptada a cuenta pequeña
        self.min_profit_threshold = 0.3  # 0.3% mínimo de ganancia
        self.max_position_size = 25  # USD por operación
        self.max_daily_trades = 20  # Límite para versión gratuita de GitHub
        self.trading_pairs = [
            'XBTUSD', 'ETHUSD', 'XBTEUR', 'ETHEUR',
            'XBTUSDT', 'ETHUSDT', 'ADAUSD', 'SOLUSD'
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
            
            spread = ((ticker['ask'] - ticker['bid']) / ticker['bid']) * 100
            
            # Si el spread es inusualmente alto, puede haber oportunidad
            if spread > 0.5:  # 0.5% spread anormal
                opportunities.append({
                    'type': 'spread',
                    'pair': pair,
                    'bid': ticker['bid'],
                    'ask': ticker['ask'],
                    'spread_pct': spread,
                    'timestamp': datetime.now().isoformat()
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
        msg = f"🚨 <b>Oportunidad Detectada</b>\n"
        msg += f"Tipo: {opportunity['type']}\n"
        
        if opportunity['type'] == 'triangular':
            msg += f"Ruta: {opportunity['path']}\n"
            msg += f"Ganancia estimada: {opportunity['profit_pct']:.2f}%\n"
        elif opportunity['type'] == 'spread':
            msg += f"Par: {opportunity['pair']}\n"
            msg += f"Spread: {opportunity['spread_pct']:.2f}%\n"
        
        self.send_telegram(msg)
        
        # Por seguridad, NO ejecutar automáticamente con cuenta real pequeña
        # Solo notificar y registrar
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
            
            if total_opps == 0:
                self.send_telegram("✅ Análisis completado. No se encontraron oportunidades.")
            else:
                msg = f"📊 <b>Oportunidades encontradas: {total_opps}</b>\n\n"
                
                for opp in triangular_opps[:3]:  # Mostrar top 3
                    msg += f"🔺 Triangular\n"
                    msg += f"Ruta: {opp['path']}\n"
                    msg += f"Ganancia: {opp['profit_pct']:.2f}%\n\n"
                
                for opp in spread_opps[:3]:
                    msg += f"📈 Spread\n"
                    msg += f"Par: {opp['pair']}\n"
                    msg += f"Spread: {opp['spread_pct']:.2f}%\n\n"
                
                self.send_telegram(msg)
            
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
