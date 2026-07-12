print("أهلاً بيك يا عبده، البيئة شغالة!")

# اختبار بسيط: هل numpy متثبت؟
try:
	import numpy as np
	print("numpy موجود، النسخة:", np.__version__)
except ImportError:
	print("numpy لسه مش متثبت — طبيعي، هنثبته لاحقًا")

