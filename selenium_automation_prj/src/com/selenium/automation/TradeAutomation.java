package com.selenium.automation;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.StringTokenizer;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.openqa.selenium.By;
import org.openqa.selenium.ie.InternetExplorerDriver;
import org.openqa.selenium.ie.InternetExplorerDriverLogLevel;
import org.openqa.selenium.ie.InternetExplorerDriverService;


public class TradeAutomation {

	private InternetExplorerDriver driver;
	private static String baseUrl, uid, pwd,ieDriverPath;	
	private static List<PolicyFundsPojo> policyFundsList = null;
	private static List<PolicyFundsPojo> irPolicyFundsList = null;
	private static Map policyMap = null;

	public static void main(String args[]) throws Exception {

		TradeAutomation TradeAutomation = new TradeAutomation();
		System.out.println(" Reading XLSX");
		System.out.println(" Reading Done :");
		policyMap = new TestCaseCredentials().policyFundReader("VAR_AFCT.xlsx");
		if(policyMap != null) {				
			TradeAutomation.setUp();
			TradeAutomation.startTrade(policyMap);
		}		
		else {
			System.out.println("No policies to process trade automation");
		}	

	}


	public void setUp() throws Exception {

		Properties prop = new Properties();
		InputStream input = null;

		try {
			input = new FileInputStream("navisys.properties");
			prop.load(input);
			TradeAutomation.baseUrl = prop.getProperty("baseUrl");
			TradeAutomation.uid = prop.getProperty("uid");
			TradeAutomation.pwd = prop.getProperty("pwd");		
			TradeAutomation.ieDriverPath = prop.getProperty("ieDriverPath");
			//File driverFile = new File(TradeAutomation.ieDriverPath);
			//System.setProperty("webdriver.ie.driver", driverFile.getAbsolutePath());
			InternetExplorerDriverService.Builder serviceBuilder = new InternetExplorerDriverService.Builder();
			serviceBuilder.usingAnyFreePort(); // This specifies that sever can pick any available free port to start
			serviceBuilder.usingDriverExecutable(new File(TradeAutomation.ieDriverPath));
			serviceBuilder.withLogLevel(InternetExplorerDriverLogLevel.TRACE); // Specifies the log level of the server
			serviceBuilder.withLogFile(new File("logs/logFile.txt")); // Specify the log file.
			InternetExplorerDriverService service = serviceBuilder.build(); // Create a driver service and pass it to
			// Internet explorer driver instance
			driver = new InternetExplorerDriver(service);

		} catch (IOException ex) {
			ex.printStackTrace();
		} finally {
			if (input != null) {
				try {
					input.close();
				} catch (IOException e) {
					e.printStackTrace();
				}
			}
		}
	}

	public void startTrade(Map policyMap) throws Exception {

		try {
			driver.manage().window().maximize();
			driver.navigate().to(TradeAutomation.baseUrl + "/Login.jsp");		
			driver.findElement(By.id("userid")).clear();
			driver.findElement(By.id("userid")).sendKeys(uid);
			//driver.executeScript("document.getElementById('userid').setAttribute('value',uid)"); 
			driver.findElement(By.id("password")).clear();
			driver.findElement(By.id("password")).sendKeys(pwd);
			//driver.executeScript("document.getElementById('password').setAttribute('value',pwd)"); 				
			driver.findElement(By.name("B12")).click();
			driver.manage().timeouts().implicitlyWait(10, TimeUnit.SECONDS);	
			policyFundsList = (List<PolicyFundsPojo>)policyMap.get("normalPolicies");
			irPolicyFundsList = (List<PolicyFundsPojo>)policyMap.get("irPolicies");	
			driver.get(TradeAutomation.baseUrl + "/account/AccountTxnHistory.jsp");
			driver.manage().window().maximize();
			if (policyFundsList != null) {		
				System.out.println("Processing Normal-------->Policies");
				long startTime = System.currentTimeMillis();
				for (PolicyFundsPojo policyFund : policyFundsList) {
					System.out.println(" IR "+policyFund.getPolicyNumber()+" Source Funds :"+policyFund.getSourceFunds()+" Target Fund :"+policyFund.getTargetFund());
					processTrade(policyFund,false);			
				}	
				long endTime = System.currentTimeMillis();
				
				System.out.println("Time Taken for "+policyFundsList.size()+" normal policies :"+(endTime-startTime));
			} else {
				System.out.println("No Normal policies to process trade automation");
			}

			if (irPolicyFundsList != null) {	
				System.out.println("Processing IR-------->Policies");
				long startTime = System.currentTimeMillis();
				for (PolicyFundsPojo irPolicyFund : irPolicyFundsList) {
					System.out.println(" IR "+irPolicyFund.getPolicyNumber()+" Source Funds :"+irPolicyFund.getSourceFunds()+" Target Fund :"+irPolicyFund.getTargetFund());					
					processTrade(irPolicyFund,true);	
				}
				long endTime = System.currentTimeMillis();
				
				System.out.println("Time Taken for "+irPolicyFundsList.size()+" IR policies :"+(endTime-startTime));
			} else {
				System.out.println("No IR policies to process trade automation");
			}
			driver.close();
			driver.quit();
		} catch (Exception e) {
			System.out.println("Web Element unavailable");
			driver.close();
			driver.quit();
		}

	}

	public void processTrade(PolicyFundsPojo policyFund,boolean isIR)
	{
		
		driver.findElement(By.name("headerAccountNumber")).click();
		driver.findElement(By.name("headerAccountNumber")).clear();
		driver.findElement(By.name("headerAccountNumber")).sendKeys(policyFund.getPolicyNumber());
		//driver.executeScript("document.getElementById('headerAccountNumber').setAttribute('value','" + policyFund.getPolicyNumber() + "')");
		driver.findElement(By.name("Go")).click();
		driver.get(TradeAutomation.baseUrl + "/account/AccountTxnHistory.jsp");
		driver.findElement(By.name("addTransType")).click();
		driver.findElement(By.xpath("//option[@value='17']")).click();
		driver.findElement(By.name("Add")).click();
		
		if(isIR)
		{
			WebElement suppressFRRElement = driver.findElement(By.name("suppressFRR"));
			WebElement overRideIRElement = driver.findElement(By.name("overRideIR"));
			if(!suppressFRRElement.isSelected())
				suppressFRRElement.click();
			if(!overRideIRElement.isSelected())
				overRideIRElement.click();
		}
		
		findFundsForPolicy(policyFund.getPolicyNumber(), policyFund.getSourceFunds(), policyFund.getTargetFund());		
	}

	void findFundsForPolicy(String policy, String sourceFunds, String targetFund) {
		
		try {			
			WebElement suppressConfirmElement = driver.findElement(By.name("suppressConfirms"));
			if(!suppressConfirmElement.isSelected())
				suppressConfirmElement.click();			
			StringTokenizer sourceFundsToken = new StringTokenizer(sourceFunds, ",");			
			String str = driver.findElement(By.id("fundDisplayArea")).getAttribute("innerHTML");
			//System.out.println(str);			
			while (sourceFundsToken.hasMoreElements()) {				
				String partialSourceFundId = sourceFundsToken.nextElement().toString();
				String completeSourceFundId = getFundIDbyRegex(str,partialSourceFundId);				
				driver.findElement(By.name(completeSourceFundId)).sendKeys("-100");
				//driver.executeScript("driver.findElement(By.name(" + sourceFundsToken.nextElement().toString() + ")).sendKeys('-100')");
			}		

			String completeTargetFund = getFundIDbyRegex(str,targetFund);
			//System.out.println(targetFund);
			driver.findElement(By.name(completeTargetFund)).sendKeys("100");
			//	driver.executeScript("driver.findElement(By.name(" + targetFund + ")).sendKeys('-100')");
			driver.findElement(By.name("Continue")).click();
			driver.findElement(By.name("Processr")).click();	
			System.out.println("Trade success for Policy :"+policy+" and source funds are :"+sourceFunds+" Targeted Fund :"+targetFund);
		} catch (Exception e) {
			System.out.println("Fund Element unavailable");
		}
	}

	/*public void fundAssign(String sfund) {
		try {

			driver.findElement(By.name(sfund)).sendKeys("-100");
			System.out.println("****** FOUND THE FUND " + sfund);
		} catch (Exception e) {
			System.out.println("!!!!!! NOT FOUND THE FUND " + sfund);
		}

	}*/

	public static String getFundIDbyRegex(String content, String nameid) {
		String pattern = "name=[\"\']?(" + nameid + "[^ >\"\']*)[\"\']?[ >]";
		Pattern r = Pattern.compile(pattern);
		Matcher m = r.matcher(content);
		if (m.find( )) {
			return m.group(1);
		}else {
			return "Not Found";
		}
	}




}
