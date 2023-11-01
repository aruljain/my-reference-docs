package com.svp;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.xssf.usermodel.XSSFSheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;

public class SVPController {
	String gitUrls[]; 
	List<String> filesListInDir = new ArrayList<String>();
	
	public void readXlsx() throws Exception
	{
		FileInputStream fis=new FileInputStream(new File("C:\\soft\\sample7.xlsx"));  
		//creating workbook instance that refers to .xls file  
		XSSFWorkbook wb = new XSSFWorkbook(fis);   
		XSSFSheet sheet = wb.getSheetAt(0);     
		System.out.println("Total rows are :"+sheet.getLastRowNum());
		//System.out.println(sheet.getRow(0)+
		int rowNums = sheet.getLastRowNum();
		gitUrls = new String[rowNums];
		for(int i=1;i<=sheet.getLastRowNum();i++) {
		Row row=sheet.getRow(i); //returns the logical row  
		//Cell cell=row.getCell(0); //getting the cell representing the given column  
	
		gitUrls[i-1] = row.getCell(1).getStringCellValue();
		System.out.println(row.getCell(0).getStringCellValue()
			+"  "+row.getCell(1).getStringCellValue()+"  "+row.getCell(2).getStringCellValue()+"----->"+getRepoName(gitUrls[i-1]));    //g
		}
	}
	
	public void cloneGit() throws IOException {
		
		for(String giturl : gitUrls) {				
			String repoName = getRepoName(giturl);
			System.out.println("======> :"+repoName);
		String cmd = "git clone "+giturl+" c:\\soft\\testclone\\"+repoName+"\\";
		 Runtime.getRuntime().exec(cmd);
		 File dir = new File("c:\\soft\\testclone\\"+repoName);
	        String zipDirName = "c:\\soft\\testclone\\"+repoName+".zip";
	        zipDirectory(dir, zipDirName);
		}
}
	public String getRepoName(String gitUrl)
	{
		 String repoName = null;
		String strPattern[] = { "([^/]+)\\.git$" };
        for (int i = 0; i < strPattern.length; i++) {
            Pattern pattern
                = Pattern.compile(strPattern[i]);
            Matcher matcher = pattern.matcher(gitUrl);
            while (matcher.find()) {
                System.out.println(matcher.group().split("\\.", 2)[0]);
                 repoName = matcher.group().split("\\.", 2)[0];
                return repoName;
            }
        }
        return repoName;
	}
	
	private void zipDirectory(File dir, String zipDirName) {
        try {
            populateFilesList(dir);
            //now zip files one by one
            //create ZipOutputStream to write to the zip file
            FileOutputStream fos = new FileOutputStream(zipDirName);
            ZipOutputStream zos = new ZipOutputStream(fos);
            for(String filePath : filesListInDir){
                System.out.println("Zipping "+filePath);
                //for ZipEntry we need to keep only relative file path, so we used substring on absolute path
                ZipEntry ze = new ZipEntry(filePath.substring(dir.getAbsolutePath().length()+1, filePath.length()));
                zos.putNextEntry(ze);
                //read the file and write to ZipOutputStream
                FileInputStream fis = new FileInputStream(filePath);
                byte[] buffer = new byte[1024];
                int len;
                while ((len = fis.read(buffer)) > 0) {
                    zos.write(buffer, 0, len);
                }
                zos.closeEntry();
                fis.close();
            }
            zos.close();
            fos.close();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
    
    /**
     * This method populates all the files in a directory to a List
     * @param dir
     * @throws IOException
     */
    private void populateFilesList(File dir) throws IOException {
        File[] files = dir.listFiles();
        for(File file : files){
            if(file.isFile()) filesListInDir.add(file.getAbsolutePath());
            else populateFilesList(file);
        }
    }

	
	public static void main(String args[]) throws Exception
	{
				SVPController svpController = 	new SVPController();
				svpController.readXlsx();
				svpController.cloneGit();
				 
		
	}


}
