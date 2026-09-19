package uz.maktab.hisobot;

import android.app.*;
import android.os.*;
import android.graphics.Color;
import android.view.*;
import android.widget.*;
import android.text.InputType;
import android.content.Intent;
import android.net.Uri;
import android.graphics.drawable.GradientDrawable;
import org.json.*;
import java.net.*;
import java.io.*;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.*;

/** Native Android pilot; backend URL must use HTTPS. Tokens only in memory. */
public class MainActivity extends Activity {
    LinearLayout page; String base="", token="", role="", loginName="";
    final ExecutorService pool=Executors.newSingleThreadExecutor();
    String[] reasons={"Kelgan"};
    JSONObject school=new JSONObject(); String pdfPath=""; Runnable draftSaver=null;
    interface Task { JSONObject run() throws Exception; }
    interface Done { void run(JSONObject result) throws Exception; }
    @Override public void onCreate(Bundle b){super.onCreate(b); getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE); login();}
    void screen(String title){
        draftSaver=null;
        ScrollView scroll=new ScrollView(this); page=new LinearLayout(this);page.setOrientation(LinearLayout.VERTICAL);page.setPadding(30,40,30,40);page.setBackgroundColor(Color.rgb(244,247,252));scroll.addView(page);setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v,insets)->{page.setPadding(30,Math.max(40,insets.getSystemWindowInsetTop()+15),30,Math.max(30,insets.getSystemWindowInsetBottom()+15));return insets;});
        TextView header=label(title);header.setTextSize(26);header.setTextColor(Color.rgb(18,55,92));
    }
    TextView label(String s){TextView t=new TextView(this);t.setText(s);t.setTextSize(16);t.setPadding(0,12,0,12);page.addView(t);return t;}
    EditText input(String hint,String value){EditText e=new EditText(this);e.setHint(hint);e.setText(value);e.setSingleLine(true);page.addView(e);return e;}
    Button button(String text,Runnable action){Button b=new Button(this);b.setText(text);b.setAllCaps(false);b.setTextSize(15);b.setTextColor(Color.WHITE);GradientDrawable bg=new GradientDrawable();bg.setColor(Color.rgb(27,81,134));bg.setCornerRadius(16);b.setBackground(bg);LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,12,0,8);b.setPadding(20,22,20,22);page.addView(b,lp);b.setOnClickListener(v->action.run());return b;}
    void message(String s){new AlertDialog.Builder(this).setMessage(s).setPositiveButton("Tushunarli",null).show();}
    JSONObject json(Object... args)throws Exception{JSONObject j=new JSONObject();for(int i=0;i<args.length;i+=2)j.put(args[i].toString(),args[i+1]);return j;}
    JSONObject api(String path,JSONObject data)throws Exception{
        URL url=new URL(base+path);checkUrl(url);
        HttpURLConnection c=(HttpURLConnection)url.openConnection();c.setConnectTimeout(12000);c.setReadTimeout(20000);c.setInstanceFollowRedirects(false);
        c.setRequestProperty("Authorization","Bearer "+token);
        try{
            if(data!=null){c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");try(OutputStream out=c.getOutputStream()){out.write(data.toString().getBytes("UTF-8"));}}
            int code=c.getResponseCode();InputStream in=code<400?c.getInputStream():c.getErrorStream();
            if(in==null)throw new IOException("Server javob bermadi: "+code);
            ByteArrayOutputStream buffer=new ByteArrayOutputStream();try(InputStream stream=in){byte[] bytes=new byte[4096];int n;while((n=stream.read(bytes))!=-1)buffer.write(bytes,0,n);}
            JSONObject result=new JSONObject(buffer.toString("UTF-8"));if(code!=200)throw new IOException(result.optString("error","Server xatosi"));return result;
        }finally{c.disconnect();}
    }
    void work(Task t,Done done){
        ProgressDialog d=ProgressDialog.show(this,"","Yuklanmoqda…",true,false);
        pool.execute(()->{try{JSONObject r=t.run();runOnUiThread(()->{if(isFinishing())return;d.dismiss();try{done.run(r);}catch(Exception e){message(e.getMessage());}});}catch(Exception e){runOnUiThread(()->{if(isFinishing())return;d.dismiss();message(e.getMessage()==null?"Ulanish xatosi":e.getMessage());});}});
    }
    void checkUrl(URL url)throws IOException{
        if(url.getProtocol().equals("https"))return;
        String host=url.getHost();boolean local=host.equals("localhost")||host.equals("127.0.0.1");
        String[] parts=host.split("\\.");
        try{if(parts.length==4){int a=Integer.parseInt(parts[0]),b=Integer.parseInt(parts[1]);boolean valid=true;for(String part:parts){int v=Integer.parseInt(part);if(v<0||v>255)valid=false;}local=valid&&(a==10||(a==192&&b==168)||(a==172&&b>=16&&b<=31)||a==127);}}catch(NumberFormatException ignored){}
        if(BuildConfig.DEBUG&&url.getProtocol().equals("http")&&local)return;
        throw new IOException("HTTPS server kerak. Sinov APKda mahalliy IP uchun HTTP mumkin.");
    }
    void login(){
        screen("Maktab Hisobot");label("Sinf rahbari, direktor o‘rinbosari va tuman xodimi");if(BuildConfig.DEBUG)label("SINOV VERSIYASI • Mahalliy tarmoq yoki HTTPS server");
        EditText server=input("https://hisobot.example.uz",getPreferences(0).getString("server",""));
        EditText schoolCode=input("Maktab yoki tuman kodi (XOJ-09 yoki XOJ)",getPreferences(0).getString("school",""));
        EditText user=input("Login","");EditText password=input("Parol","");password.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        button("Kirish",()->{base=server.getText().toString().trim().replaceAll("/+$","");loginName=user.getText().toString().trim();String enteredPassword=password.getText().toString();String code=schoolCode.getText().toString().trim();work(()->api("/login",json("school",code,"login",loginName,"password",enteredPassword)),r->{token=r.getString("token");role=r.getString("role");getPreferences(0).edit().putString("server",base).putString("school",r.optString("school",code)).apply();home();});});
    }
    void home(){work(()->api("/classes",null),r->{
        if(role.equals("district")||"district".equals(r.optString("kind"))){districtHome(r);return;}
        JSONArray catalog=r.getJSONArray("reasons");reasons=new String[catalog.length()];for(int j=0;j<catalog.length();j++)reasons[j]=catalog.getString(j);school=r.getJSONObject("school");
        screen("Maktab Hisobot");label(school.optString("name")+(school.optString("code").isEmpty()?"":"  •  "+school.optString("code")));label(role.equals("admin")?"Direktor o‘rinbosari":"Mening sinflarim");
        if(role.equals("admin")){EditText day=input("Sana YYYY-MM-DD",LocalDate.now().toString());button("Kunlik jamlangan hisobot",()->summary(day.getText().toString()));
            button("Oylik hisobot va taqvim",this::monthMenu);button("Maktab ma’lumotlari",this::settings);button("O‘qituvchilar va sinflar",this::manage);}
        JSONArray classes=r.getJSONArray("classes");for(int i=0;i<classes.length();i++){JSONObject cl=classes.getJSONObject(i);int id=cl.getInt("id");String name=cl.getString("name");button(name,()->classMenu(id,name));}
        button("Parolni almashtirish",this::password);
        button("Chiqish",()->work(()->api("/logout",json()),x->{token="";login();}));
    });}
    void districtHome(JSONObject r)throws Exception{
        JSONObject district=r.optJSONObject("district");if(district==null)district=r.optJSONObject("school");
        screen("Tuman Hisobot");label(district.optString("name")+"  •  "+district.optString("code"));
        label("Faqat shu tuman maktablari. O‘quvchi ro‘yxati tuman xodimiga ochilmaydi. Har maktab 12:00 da o‘z Telegramiga PDF yuboradi.");
        EditText day=input("Sana YYYY-MM-DD",r.optString("day",LocalDate.now().toString()));
        JSONArray schools=r.optJSONArray("schools");if(schools==null)schools=new JSONArray();
        ArrayList<Integer> ids=new ArrayList<>();ArrayList<String> names=new ArrayList<>();
        for(int i=0;i<schools.length();i++){
            JSONObject sch=schools.getJSONObject(i);ids.add(sch.getInt("id"));names.add(sch.optString("code")+" — "+sch.optString("name"));
            JSONObject admin=sch.optJSONObject("admin");String who=admin==null?"direktor o‘rinbosari yo‘q":admin.optString("name")+" ("+admin.optString("login")+")";
            label(sch.optString("code")+"  "+sch.optString("name")+"\nJo‘natgan sinflar: "+sch.optInt("submitted")+" / "+sch.optInt("classes")+"\n"+who+(sch.optBoolean("telegram_configured")?"\nTelegram ulangan":"\nTelegram ulanmagan"));
        }
        if(schools.length()==0)label("Hali maktab yo‘q. Pastdan qo‘shing.");
        button("Holatni yangilash",()->{String d=day.getText().toString().trim();work(()->api("/classes?day="+d,null),this::districtHome);});
        label("Yangi maktab");EditText scode=input("Maktab kodi, masalan XOJ-09","");EditText sname=input("Maktabning to‘liq nomi","");
        EditText director=input("Direktor F.I.Sh.","");EditText executor=input("Ijrochi F.I.Sh.","");
        button("Maktabni qo‘shish",()->work(()->api("/schools",json("code",scode.getText().toString(),"name",sname.getText().toString(),"director",director.getText().toString(),"executor",executor.getText().toString())),this::districtHome));
        label("Direktor o‘rinbosari hisobi");Spinner pick=new Spinner(this);pick.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,names));page.addView(pick);
        EditText aname=input("F.I.Sh.","");EditText alogin=input("Login","");EditText apass=input("Parol — kamida 10 belgi","");apass.setInputType(129);
        button("Hisobni saqlash",()->{if(ids.isEmpty()){message("Avval maktab qo‘shing");return;}work(()->api("/schools/admin",json("school_id",ids.get(pick.getSelectedItemPosition()),"name",aname.getText().toString(),"login",alogin.getText().toString(),"password",apass.getText().toString())),this::districtHome);});
        button("Parolni almashtirish",this::password);
        button("Chiqish",()->work(()->api("/logout",json()),x->{token="";login();}));
    }
    void classMenu(int id,String name){
        screen(name+" sinf");EditText day=input("Hisobot sanasi",LocalDate.now().toString());
        button("Davomatni belgilash",()->attendance(id,name,day.getText().toString()));
        button("O‘quvchilar ro‘yxati",()->students(id,name));button("O‘quvchi qo‘shish",()->addStudent(id,name));button("Bosh sahifa",this::home);
    }
    void addStudent(int id,String name){
        screen("O‘quvchi qo‘shish • "+name);EditText full=input("Familiya, ism, otasining ismi","");EditText address=input("Yashash manzili","");
        Spinner gender=new Spinner(this);gender.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"O‘g‘il","Qiz"}));page.addView(gender);
        button("Saqlash",()->work(()->api("/students",json("class_id",id,"name",full.getText().toString(),"address",address.getText().toString(),"gender",gender.getSelectedItemPosition()==0?"M":"F")),r->{message("O‘quvchi qo‘shildi");classMenu(id,name);}));button("Orqaga",()->classMenu(id,name));
    }
    String draftKey(int id,String day){return "draft:v3:"+base+":"+getPreferences(0).getString("school","")+":"+loginName+":"+id+":"+day;}
    void attendance(int id,String name,String day){
        try{LocalDate.parse(day);}catch(Exception e){message("Sana YYYY-MM-DD formatida bo‘lsin");return;}
        work(()->{JSONObject r=api("/report?class_id="+id+"&day="+day,null);r.put("students",api("/students?class_id="+id,null).getJSONArray("students"));return r;},r->{
            screen(name+" • "+day);label("Har bir o‘quvchini tekshiring, kelmaganlar sababini belgilang.");
            final int revision=r.getInt("revision");JSONArray pupils=revision>0?r.getJSONArray("entries"):r.getJSONArray("students");
            if(r.optBoolean("locked")){label("Hisobot tasdiqlangan. O‘zgartirish uchun direktor qayta ochishi kerak.");button("Orqaga",()->classMenu(id,name));return;}
            JSONArray previous=r.getJSONArray("entries");String draft=DraftStore.read(this,draftKey(id,day));
            if(!draft.isEmpty()){JSONObject saved=new JSONObject(draft);if(saved.getInt("revision")==revision){previous=saved.getJSONArray("entries");label("Telefondagi qoralama tiklandi");}else{label("Server yangilangan. Eski qoralama qo‘llanmadi.");}}
            Map<Integer,JSONObject> old=new HashMap<>();for(int i=0;i<previous.length();i++)old.put(previous.getJSONObject(i).getInt("id"),previous.getJSONObject(i));
            ArrayList<Spinner> statuses=new ArrayList<>();ArrayList<EditText> notes=new ArrayList<>();ArrayList<Integer> ids=new ArrayList<>();
            for(int i=0;i<pupils.length();i++){
                JSONObject pupil=pupils.getJSONObject(i);int sid=pupil.getInt("id");ids.add(sid);label((i+1)+". "+pupil.getString("name"));
                Spinner s=new Spinner(this);s.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,reasons));s.setSelection(old.containsKey(sid)?old.get(sid).getInt("status"):0);page.addView(s);statuses.add(s);
                notes.add(input("Izoh (ixtiyoriy)",old.containsKey(sid)?old.get(sid).optString("note"):""));
            }
            Task collect=()->{JSONArray entries=new JSONArray();for(int i=0;i<ids.size();i++)entries.put(json("id",ids.get(i),"status",statuses.get(i).getSelectedItemPosition(),"note",notes.get(i).getText().toString()));return json("class_id",id,"day",day,"revision",revision,"entries",entries);};
            Runnable saveDraft=()->{try{DraftStore.save(this,draftKey(id,day),collect.run().toString());message("Qoralama telefonda saqlandi. Hali yuborilmadi.");}catch(Exception e){message(e.getMessage());}};
            draftSaver=()->{try{DraftStore.save(this,draftKey(id,day),collect.run().toString());}catch(Exception ignored){}};
            button("Qoralamani saqlash",saveDraft);
            CheckBox confirm=new CheckBox(this);confirm.setText(R.string.confirm_attendance);page.addView(confirm);
            button("Hisobotni jo‘natish",()->{
                if(!confirm.isChecked()){message("Avval davomatni tekshirganingizni tasdiqlang");return;}
                try{JSONObject payload=collect.run();DraftStore.save(this,draftKey(id,day),payload.toString());work(()->api("/report",payload),result->{draftSaver=null;DraftStore.remove(this,draftKey(id,day));classMenu(id,name);message("Hisobot saqlandi. Kunlik jamlanma soat 12:00 da direktor o‘rinbosari Telegramiga yuboriladi.");});}catch(Exception e){message(e.getMessage());}
            });button("Orqaga",()->new AlertDialog.Builder(this).setMessage("Saqlanmagan belgilar yo‘qoladi. Orqaga qaytasizmi?").setPositiveButton("Ha",(a,b)->classMenu(id,name)).setNegativeButton("Qolish",null).show());
        });
    }
    void summary(String day){
        try{LocalDate.parse(day);}catch(Exception e){message("Sana noto‘g‘ri");return;}
        work(()->api("/summary?day="+day,null),r->{
            screen("Jamlangan hisobot");label(day);label("Avtomatik yuborish: har kuni soat 12:00, 3 varaqli PDF.");if(!r.optBoolean("telegram_configured"))label("Telegram hali serverda ulanmagan. PDF navbatda saqlanadi.");JSONArray rows=r.getJSONArray("rows");int present=0,absent=0,missing=0;
            for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(!row.getBoolean("submitted")){missing++;label(row.getString("class")+" — HISOBOT KUTILMOQDA");continue;}
                JSONArray c=row.getJSONArray("counts");int p=c.getInt(0),a=row.getInt("total")-p;present+=p;absent+=a;label(row.getString("class")+": "+p+" kelgan / "+a+" kelmagan");
                final JSONObject report=row;button(row.getString("class")+" — "+(row.optBoolean("locked")?"Qayta ochish":"Tasdiqlash"),()->work(()->api("/report/lock",json("day",day,"class_id",report.getInt("id"),"revision",report.getInt("revision"),"locked",!report.optBoolean("locked"))),x->summary(day)));}
            label("Jami topshirganlar: "+present+" kelgan, "+absent+" kelmagan. Kutilayotgan sinflar: "+missing);
            JSONArray jobs=r.getJSONArray("telegram");for(int i=0;i<Math.min(3,jobs.length());i++){JSONObject j=jobs.getJSONObject(i);label("Telegram #"+j.getInt("id")+": "+(j.getString("state").equals("sent")?"Yetkazildi":"Navbatda")+" • urinish: "+j.getInt("attempts"));}
            button("PDFni direktor Telegramiga yuborish",()->new AlertDialog.Builder(this).setMessage("Shu sana hisoboti belgilangan direktor akkauntiga yuborilsinmi?").setPositiveButton("Yuborish",(a,b)->work(()->api("/telegram",json("day",day)),x->{message(x.getString("message"));})).setNegativeButton("Bekor qilish",null).show());
            button("PDFni telefonga saqlash",()->savePdf("/pdf?day="+day,"Hisobot-"+day+".pdf"));
            button("Holatni yangilash",()->summary(day));button("Bosh sahifa",this::home);
        });
    }
    void students(int cid,String className){work(()->api("/students?class_id="+cid,null),r->{
        screen(className+" • O‘quvchilar");JSONArray rows=r.getJSONArray("students");
        for(int i=0;i<rows.length();i++){JSONObject pupil=rows.getJSONObject(i);button(pupil.getString("name"),()->editStudent(cid,className,pupil));}
        button("Yangi o‘quvchi",()->addStudent(cid,className));button("Orqaga",()->classMenu(cid,className));
    });}
    void editStudent(int cid,String className,JSONObject pupil){
        screen("O‘quvchi ma’lumotlari");EditText name=input("F.I.Sh.",pupil.optString("name"));EditText address=input("Yashash manzili",pupil.optString("address"));
        Spinner gender=new Spinner(this);gender.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"O‘g‘il","Qiz"}));gender.setSelection(pupil.optString("gender").equals("F")?1:0);page.addView(gender);
        button("O‘zgarishlarni saqlash",()->{try{JSONObject data=json("id",pupil.getInt("id"),"name",name.getText().toString(),"address",address.getText().toString(),"gender",gender.getSelectedItemPosition()==0?"M":"F");work(()->api("/students/update",data),r->students(cid,className));}catch(Exception e){message(e.getMessage());}});
        button("O‘quvchini arxivlash",()->new AlertDialog.Builder(this).setMessage("Faol ro‘yxatdan olinadi. Oldingi hisobotlar saqlanadi.").setPositiveButton("Arxivlash",(a,b)->work(()->api("/students/archive",json("id",pupil.getInt("id"))),r->students(cid,className))).setNegativeButton("Bekor",null).show());
        button("Orqaga",()->students(cid,className));
    }
    void settings(){work(()->api("/settings",null),r->{
        JSONObject values=r.getJSONObject("school");screen("Maktab sozlamalari");
        EditText name=input("Maktabning to‘liq nomi",values.optString("name"));EditText director=input("Direktor F.I.Sh.",values.optString("director"));EditText executor=input("Ijrochi F.I.Sh.",values.optString("executor"));
        label(r.optBoolean("telegram_configured")?"Telegram serverda sozlangan. Kunlik PDF soat 12:00 da ketadi.":"Telegram serverda hali sozlanmagan");
        label("Maktab kodi: "+values.optString("code"));
        button("Saqlash",()->{try{JSONObject data=json("name",name.getText().toString(),"director",director.getText().toString(),"executor",executor.getText().toString());work(()->api("/settings",data),x->home());}catch(Exception e){message(e.getMessage());}});button("Orqaga",this::home);
    });}
    void manage(){work(()->api("/users",null),r->{
        screen("O‘qituvchilar va sinflar");JSONArray users=r.getJSONArray("users");
        label("Yangi o‘qituvchi hisobi");EditText full=input("Sinf rahbari F.I.Sh.","");EditText user=input("Login","");EditText pass=input("Parol — kamida 10 belgi","");pass.setInputType(129);
        button("O‘qituvchi yaratish",()->{try{JSONObject data=json("name",full.getText().toString(),"login",user.getText().toString(),"password",pass.getText().toString());work(()->api("/users",data),x->manage());}catch(Exception e){message(e.getMessage());}});
        label("Yangi sinfni biriktirish");EditText name=input("Sinf, masalan 7-A","");ArrayList<String> names=new ArrayList<>();ArrayList<Integer> ids=new ArrayList<>();
        for(int i=0;i<users.length();i++){JSONObject u=users.getJSONObject(i);if(u.getString("role").equals("teacher")){String shown=u.optString("name");names.add((shown.isEmpty()?u.getString("login"):shown)+" ("+u.getString("login")+")");ids.add(u.getInt("id"));}}
        Spinner teacher=new Spinner(this);teacher.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,names));page.addView(teacher);
        button("Sinf yaratish",()->{if(ids.isEmpty()){message("Avval o‘qituvchi yarating");return;}try{JSONObject data=json("name",name.getText().toString(),"teacher_id",ids.get(teacher.getSelectedItemPosition()));work(()->api("/classes/create",data),x->home());}catch(Exception e){message(e.getMessage());}});
        label("O‘qituvchi parolini tiklash");EditText reset=input("Yangi parol","");reset.setInputType(129);
        button("Tanlangan o‘qituvchi parolini almashtirish",()->{if(ids.isEmpty())return;try{JSONObject data=json("id",ids.get(teacher.getSelectedItemPosition()),"password",reset.getText().toString());work(()->api("/users/reset",data),x->message("Parol yangilandi. O‘qituvchi qayta kirishi kerak."));}catch(Exception e){message(e.getMessage());}});
        button("Orqaga",this::home);
    });}
    void password(){
        screen("Parolni almashtirish");EditText old=input("Joriy parol","");old.setInputType(129);EditText fresh=input("Yangi parol — kamida 10 belgi","");fresh.setInputType(129);
        button("Saqlash",()->{try{JSONObject data=json("current",old.getText().toString(),"password",fresh.getText().toString());work(()->api("/password",data),r->{token="";login();message("Parol yangilandi. Qayta kiring.");});}catch(Exception e){message(e.getMessage());}});button("Orqaga",this::home);
    }
    void monthMenu(){
        screen("Oylik hisobot");EditText month=input("Oy YYYY-MM",LocalDate.now().toString().substring(0,7));
        button("Hisobotni ko‘rish",()->monthly(month.getText().toString()));button("O‘quv kunlarini belgilash",()->calendar(month.getText().toString()));button("Orqaga",this::home);
    }
    void calendar(String month){
        try{java.time.YearMonth.parse(month);}catch(Exception e){message("Oy YYYY-MM formatida bo‘lsin");return;}
        work(()->api("/calendar?month="+month,null),r->{
            screen(month+" • O‘quv kunlari");label("Faqat dars o‘tiladigan kunlarni belgilang. Ta’til va dam olish kunlarini belgilangandan chiqaring.");
            HashSet<String> saved=new HashSet<>();JSONArray ds=r.getJSONArray("days");for(int i=0;i<ds.length();i++)saved.add(ds.getString(i));
            ArrayList<CheckBox> boxes=new ArrayList<>();int count=java.time.YearMonth.parse(month).lengthOfMonth();
            for(int i=1;i<=count;i++){String day=month+String.format(java.util.Locale.ROOT,"-%02d",i);CheckBox cb=new CheckBox(this);cb.setText(day);cb.setChecked(saved.contains(day));boxes.add(cb);page.addView(cb);}
            button("Taqvimni saqlash",()->{try{JSONArray days=new JSONArray();for(CheckBox cb:boxes)if(cb.isChecked())days.put(cb.getText().toString());JSONObject data=json("month",month,"days",days);work(()->api("/calendar",data),x->{monthMenu();message("Taqvim saqlandi");});}catch(Exception e){message(e.getMessage());}});button("Orqaga",this::monthMenu);
        });
    }
    void monthly(String month){
        try{java.time.YearMonth.parse(month);}catch(Exception e){message("Oy YYYY-MM formatida bo‘lsin");return;}
        work(()->api("/monthly?month="+month,null),r->{
            screen(month+" • Oylik natija");if(!r.getBoolean("calendar_configured"))label("O‘quv kunlari taqvimi kiritilmagan — oy to‘liqligi noma’lum.");
            JSONArray rows=r.getJSONArray("rows");int total=0,present=0,missing=0;
            for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(!row.getBoolean("submitted")){missing++;continue;}total+=row.getInt("total");present+=row.getJSONArray("counts").getInt(0);}
            label("Topshirilgan o‘quvchi-kunlar: "+total);label("Kelmagan o‘quvchi-kunlar: "+(total-present));label("Kutilayotgan sinf-kunlar: "+missing);label(total>0?String.format(java.util.Locale.ROOT,"Topshirilganlar bo‘yicha davomat: %.2f%%",100.0*present/total):"Foizni hisoblash uchun ma’lumot yo‘q");
            button("Oylik PDFni saqlash",()->savePdf("/monthly/pdf?month="+month,"Hisobot-"+month+".pdf"));
            button("Oylik PDFni Telegramga yuborish",()->new AlertDialog.Builder(this).setMessage("Shu oy PDF hisoboti direktor akkauntiga yuborilsinmi?").setPositiveButton("Yuborish",(a,b)->work(()->api("/monthly/telegram",json("month",month)),x->message(x.getString("message")))).setNegativeButton("Bekor",null).show());button("Orqaga",this::monthMenu);
        });
    }
    void savePdf(String path,String filename){
        pdfPath=path;Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType("application/pdf");intent.putExtra(Intent.EXTRA_TITLE,filename);startActivityForResult(intent,40);
    }
    @Override protected void onActivityResult(int req,int result,Intent data){
        super.onActivityResult(req,result,data);if(req!=40||result!=RESULT_OK||data==null)return;Uri uri=data.getData();String path=pdfPath;
        work(()->{URL url=new URL(base+path);checkUrl(url);HttpURLConnection c=(HttpURLConnection)url.openConnection();c.setConnectTimeout(12000);c.setReadTimeout(30000);c.setInstanceFollowRedirects(false);c.setRequestProperty("Authorization","Bearer "+token);
            try{if(c.getResponseCode()!=200)throw new IOException("PDFni olish imkoni bo‘lmadi. Qayta kiring.");try(InputStream in=c.getInputStream();OutputStream out=getContentResolver().openOutputStream(uri)){if(out==null)throw new IOException("Fayl ochilmadi");byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1)out.write(buffer,0,n);}}finally{c.disconnect();}return new JSONObject();},r->message("PDF saqlandi. Uni ochib chop etishingiz mumkin."));
    }
    @Override protected void onPause(){if(draftSaver!=null)draftSaver.run();super.onPause();}
    @Override public void onBackPressed(){if(draftSaver!=null)draftSaver.run();if(token.isEmpty())super.onBackPressed();else home();}
    @Override protected void onDestroy(){super.onDestroy();pool.shutdown();}
}
