# 视频
import os
import time  
# 通过 pip install 'volcengine-python-sdk[ark]' 安装方舟SDK
from volcenginesdkarkruntime import Ark

# 请确保您已将 API Key 存储在环境变量 ARK_API_KEY 中
# 初始化Ark客户端，从环境变量中读取您的API Key
client = Ark(
    # 此为默认路径，您可根据业务所在地域进行配置
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    # 从环境变量中获取您的 API Key。此为默认方式，您可根据需要进行修改
    api_key=os.environ.get("ARK_API_KEY"),
)

if __name__ == "__main__":
    print("----- create request -----")
    create_result = client.content_generation.tasks.create(
        model="doubao-seedance-1-5-pro-251215", # 模型 Model ID 已为您填入
        content=[
            {
                # 文本提示词与参数组合
                "type": "text",
                "text": "无人机以极快速度穿越复杂障碍或自然奇观，带来沉浸式飞行体验  --duration 5 --camerafixed false --watermark true"
            },
            { # 若仅需使用文本生成视频功能，可对该大括号内的内容进行注释处理，并删除上一行中大括号后的逗号。
                # 首帧图片URL
                "type": "image_url",
                "image_url": {
                    "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/seepro_i2v.png" 
                }
            }
        ]
    )
    print(create_result)

    # 轮询查询部分
    print("----- polling task status -----")
    task_id = create_result.id
    while True:
        get_result = client.content_generation.tasks.get(task_id=task_id)
        status = get_result.status
        if status == "succeeded":
            print("----- task succeeded -----")
            print(get_result)
            break
        elif status == "failed":
            print("----- task failed -----")
            print(f"Error: {get_result.error}")
            break
        else:
            print(f"Current status: {status}, Retrying after 3 seconds...")
            time.sleep(3)

# 更多操作请参考下述网址
# 查询视频生成任务列表：https://www.volcengine.com/docs/82379/1521675
# 取消或删除视频生成任务：https://www.volcengine.com/docs/82379/1521720



# 图片

curl -X POST https://ark.cn-beijing.volces.com/api/v3/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 1db5425d-b793-4df2-8898-1feb87b0f761" \
  -d '{
    "model": "doubao-seedream-5-0-260128",
    "prompt": "星际穿越，黑洞，黑洞里冲出一辆快支离破碎的复古列车，抢视觉冲击力，电影大片，末日既视感，动感，对比色，oc渲染，光线追踪，动态模糊，景深，超现实主义，深蓝，画面通过细腻的丰富的色彩层次塑造主体与场景，质感真实，暗黑风背景的光影效果营造出氛围，整体兼具艺术幻想感，夸张的广角透视效果，耀光，反射，极致的光影，强引力，吞噬",
    "sequential_image_generation": "disabled",
    "response_format": "url",
    "size": "2K",
    "stream": false,
    "watermark": true
}'

curl -X POST https://ark.cn-beijing.volces.com/api/v3/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 1db5425d-b793-4df2-8898-1feb87b0f761" \
  -d '{
    "model": "doubao-seedream-5-0-260128",
    "prompt": "生成一组共4张连贯插画，核心为同一庭院一角的四季变迁，以统一风格展现四季独特色彩、元素与氛围",
    "sequential_image_generation": "auto",
    "sequential_image_generation_options": {
        "max_images": 4
    },
    "response_format": "url",
    "size": "2K",
    "stream": true,
    "watermark": true
}'

curl -X POST https://ark.cn-beijing.volces.com/api/v3/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 1db5425d-b793-4df2-8898-1feb87b0f761" \
  -d '{
    "model": "doubao-seedream-5-0-260128",
    "prompt": "生成一组共4张连贯插画，核心为同一庭院一角的四季变迁，以统一风格展现四季独特色彩、元素与氛围",
    "sequential_image_generation": "auto",
    "sequential_image_generation_options": {
        "max_images": 4
    },
    "response_format": "url",
    "size": "2K",
    "stream": true,
    "watermark": true
}'

curl -X POST https://ark.cn-beijing.volces.com/api/v3/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 1db5425d-b793-4df2-8898-1feb87b0f761" \
  -d '{
    "model": "doubao-seedream-5-0-260128",
    "prompt": "生成一组共4张连贯插画，核心为同一庭院一角的四季变迁，以统一风格展现四季独特色彩、元素与氛围",
    "sequential_image_generation": "auto",
    "sequential_image_generation_options": {
        "max_images": 4
    },
    "response_format": "url",
    "size": "2K",
    "stream": true,
    "watermark": true
}'

curl -X POST https://ark.cn-beijing.volces.com/api/v3/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 1db5425d-b793-4df2-8898-1feb87b0f761" \
  -d '{
    "model": "doubao-seedream-5-0-260128",
    "prompt": "将图1的服装换为图2的服装",
    "image": ["https://ark-project.tos-cn-beijing.volces.com/doc_image/seedream4_imagesToimage_1.png", "https://ark-project.tos-cn-beijing.volces.com/doc_image/seedream4_imagesToimage_2.png"],
    "sequential_image_generation": "disabled",
    "response_format": "url",
    "size": "2K",
    "stream": false,
    "watermark": true
}'

curl -X POST https://ark.cn-beijing.volces.com/api/v3/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 1db5425d-b793-4df2-8898-1feb87b0f761" \
  -d '{
    "model": "doubao-seedream-5-0-260128",
    "prompt": "生成3张女孩和奶牛玩偶在游乐园开心地坐过山车的图片，涵盖早晨、中午、晚上",
    "image": ["https://ark-project.tos-cn-beijing.volces.com/doc_image/seedream4_imagesToimages_1.png", "https://ark-project.tos-cn-beijing.volces.com/doc_image/seedream4_imagesToimages_2.png"],
    "sequential_image_generation": "auto",
    "sequential_image_generation_options": {
        "max_images": 3
    },
    "response_format": "url",
    "size": "2K",
    "stream": true,
    "watermark": true
}'

# 对话
import os
from volcenginesdkarkruntime import Ark

# 从环境变量中获取您的API KEY，配置方法见：https://www.volcengine.com/docs/82379/1399008
api_key = os.getenv('ARK_API_KEY')

client = Ark(
    base_url='https://ark.cn-beijing.volces.com/api/v3',
    api_key=api_key,
)

response = client.responses.create(
    model="doubao-seed-2-0-pro-260215",
    input=[
        {
            "role": "user",
            "content": [

                {
                    "type": "input_image",
                    "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/ark_demo_img_1.png"
                },
                {
                    "type": "input_text",
                    "text": "你看见了什么？"
                },
            ],
        }
    ]
)

print(response)