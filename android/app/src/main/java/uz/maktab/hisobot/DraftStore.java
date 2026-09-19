package uz.maktab.hisobot;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Encrypts saved attendance drafts with an Android Keystore key. */
final class DraftStore {
    private static final String ALIAS="maktab_draft_v2";
    private static SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias(ALIAS)){
            KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            gen.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());gen.generateKey();
        }
        return (SecretKey)store.getKey(ALIAS,null);
    }
    static void save(Context c,String id,String value)throws Exception{
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());
        cipher.updateAAD(id.getBytes("UTF-8"));
        String packed=Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)+":"+Base64.encodeToString(cipher.doFinal(value.getBytes("UTF-8")),Base64.NO_WRAP);
        c.getSharedPreferences("secure_drafts",0).edit().putString(id,packed).apply();
    }
    static String read(Context c,String id)throws Exception{
        String packed=c.getSharedPreferences("secure_drafts",0).getString(id,"");if(packed.isEmpty())return "";
        String[] parts=packed.split(":",2);Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(parts[0],Base64.NO_WRAP)));cipher.updateAAD(id.getBytes("UTF-8"));
        return new String(cipher.doFinal(Base64.decode(parts[1],Base64.NO_WRAP)),"UTF-8");
    }
    static void remove(Context c,String id){c.getSharedPreferences("secure_drafts",0).edit().remove(id).apply();}
}
