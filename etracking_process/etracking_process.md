# E-Tracking Customs Process Guide

## Website URL
https://e-tracking.customs.go.th/ETS/

## Process Steps

### Step 1
Open the URL page, which first displays a personal information collection policy confirmation.

**![personal information policy confirmation](etracking_process/step_1.png)**

### Step 2
Click the "Accept Terms of Use"（ยอมรับเงื่อนไขการใช้งาน） checkbox, after which the page refreshes to display an "Agree" button.

**![agree](etracking_process/step_2.png)**

### Step 3
After clicking the agree"ตกลง" button, enter the main login page. click the icon_ePayment button "ระบบการพิมพ์ใบเสร็จและเอกสารทางการเงิน" in the bottom right to jump to the next page.

**![Bottom Right](etracking_process/step_3.png)**
**![icon_ePayment](etracking_process/icon_ePayment.png)**


### Step 4
After jumping to the next page, click the second item in the left menu bar "พิมพ์ใบเสร็จรับเงิน กศก.123" (Print Receipt, GSB123).

**![Print Receipt, GSB123](etracking_process/step_4.png)**

After clicking "Print Receipt, GSB123", the page jumps to "https://e-tracking.customs.go.th/ERV/ERVQ1020". Then follow these steps:

#### Step 4-1
Select "กระทํกกรรทน (สํารับนิิิบบุุค)" which represents "Legal Entity".

**![Print Receipt, GSB123](etracking_process/step_4.png)**

#### Step 4-2
Select "ผู้นําขงเา้ก/ผู้ส่งาขงขขก" which means "Importer/Exporter".

**![Print Receipt, GSB123](etracking_process/step_4.png)**

#### Step 4-3
Enter "เคาประจํิััผู้เสสียกาสขกกร" - Taxpayer Identification Number.
*Note: This is designed to be filled in after program execution on the first page (similar to the current program design).*

**![Print Receipt, GSB123](etracking_process/step_4.png)**

#### Step 4-4
After entering the taxpayer ID number, enter "000001" in the text box on the right.

**![Print Receipt, GSB123](etracking_process/step_4.png)**

#### Step 4-5
Click the "Check" button, and more information will appear on the page.

**![Print Receipt, GSB123](etracking_process/step_4.png)**

### Step 5
Fill in the relevant details:

#### Step 5-1
Fill in the printer card number "ามกีเคาบัิรผู้พิมพ์": 3101400478778

**![relevant details](etracking_process/step_5.png)**

#### Step 5-2
Fill in the company mobile number "ามกีเคาโทรศัพท์(มืขถืข)ผู้พิมพ์": 0927271000

**![relevant details](etracking_process/step_5.png)**

#### Step 5-3
Fill in the bill of lading number "เคาทส่ใบานสินุ้ก".
*Note: This should be extracted from the uploaded order number document.*

**![relevant details](etracking_process/step_5.png)**

### Step 8
验证纳税人信息。该步骤在纳税人识别号和分支码填写完成后执行，确保身份验证成功进入下一步。

#### Step 8-1
移动鼠标到校验按钮 `<button class="MuiButton-root MuiButton-contained MuiButton-containedWarning MuiButton-sizeSmall MuiButton-containedSizeSmall MuiButtonBase-root css-ztpix" tabindex="0" type="button">ตรวจสอบ</button>`，悬停鼠标于按钮上。这一步模拟人类行为，提高操作真实性。

#### Step 8-2
点击按钮"ตรวจสอบ"（校验），等待10秒钟让系统处理请求。系统验证成功后会显示新的表单元素，通过检查元素 `<h6 class="MuiTypography-root MuiTypography-h6 css-ycv6l7">ประเภทบัตรผู้พิมพ์ :</h6>` （打印卡类型）的出现确认步骤成功完成。如果该元素未出现，表示验证失败，需重试或检查输入信息。

**注意**：校验按钮点击后，系统需要时间处理请求，必须等待足够时间确保验证完成。

## Important Reference Information

| Field | Value |
|-------|-------|
| Taxpayer ID Number (เคาประจํิััผู้เสสียกาสขกกร) | 0105564083643 |
| Printer Card Number (ามกีเคาบัิรผู้พิมพ์) | 3101400478778 |
| Company Mobile Number (ามกีเคาโทรศัพท์(มืขถืข)ผู้พิมพ์) | 0927271000 |

def full_process(order_number: str):
    # Step 1: 首页弹窗同意
    wait_and_check('input#agree')
    click('button#UPDETL0050')
    # Step 2: 右下角ePayment
    wait_and_click('img#ePayImg', double=True)
    # Step 3: 左侧菜单
    wait_and_click('text=พิมพ์ใบเสร็จรับเงิน กศก.123', double=True)
    # Step 4: 表单填写
    fill_print_form(order_number)
    # Step 5: PDF导出
    export_pdf(order_number)
    # Step 8: 验证纳税人信息
    hover_and_click('button.MuiButton-contained', text='ตรวจสอบ')
    wait_for_element('h6.MuiTypography-root', text='ประเภทบัตรผู้พิมพ์ :', timeout=10000)