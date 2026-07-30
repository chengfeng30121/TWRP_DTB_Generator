BUILD_PROP="ramdisk/system/build.prop"   # 换成你找到的实际路径

# 从已知信息里提取需要的值
DEVICE="XDF-N1"
MANUFACTURER="alps"
MODEL="XDF-N1"
NAME="XDF-N1"
BRAND="XDF"

# 补上 twrpdtgen 要求的属性
echo "ro.product.system.device=${DEVICE}" >> "$BUILD_PROP"
echo "ro.product.system.manufacturer=${MANUFACTURER}" >> "$BUILD_PROP"
echo "ro.product.system.model=${MODEL}" >> "$BUILD_PROP"
echo "ro.product.system.name=${NAME}" >> "$BUILD_PROP"
echo "ro.product.system.brand=${BRAND}" >> "$BUILD_PROP"

