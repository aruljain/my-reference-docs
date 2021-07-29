package com.selenium.automation;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.apache.poi.xssf.usermodel.XSSFSheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;

public class TestCaseCredentials {
	
	public TestCaseCredentials() {	}
	
	public static void main(String args[]) {
		
		Map policyMap = null;

		List<PolicyFundsPojo> policyFundsList = null;
		List<PolicyFundsPojo> irPolicyFundsList = null;
		System.out.println(" Reading XLSX");

		policyMap = new TestCaseCredentials().policyFundReader("VAR_AFCT.xlsx");
		if(policyMap != null) {
			policyFundsList = (List<PolicyFundsPojo>)policyMap.get("normalPolicies");
			irPolicyFundsList = (List<PolicyFundsPojo>)policyMap.get("irPolicies");
			System.out.println(" Reading Done :");
				if (policyFundsList != null) {		
					System.out.println("Normal-------->Policies======================================================");
					for (PolicyFundsPojo policyFund : policyFundsList)
						System.out.println(policyFund.getPolicyNumber()+"****"+policyFund.getSourceFunds()+"***"+policyFund.getTargetFund());			
				} else {
					System.out.println("No Normal policies to process trade automation");
				}
				
				if (irPolicyFundsList != null) {	
					System.out.println("IR-------->Policies============================================================");
					for (PolicyFundsPojo irPolicyFund : irPolicyFundsList)
						System.out.println(irPolicyFund.getPolicyNumber()+"****"+irPolicyFund.getSourceFunds()+"***"+irPolicyFund.getTargetFund());			
				} else {
					System.out.println("No IR policies to process trade automation");
				}
		}
		else
		{
			System.out.println("No normal or IR policies to process trade automation");
		}
	}
		
	public Map policyFundReader(String fileAbsolutePath) {
		
		XSSFWorkbook workbook;
		XSSFSheet policyDetailsSheet,irPolicyDetailsSheet;
		List<PolicyFundsPojo> policyFundsList = null;
		List<PolicyFundsPojo> irPolicyFundsList = null;
		Map policyMap = new LinkedHashMap<>();
		try {
			File src = new File(fileAbsolutePath);
			FileInputStream fis = new FileInputStream(src);			
			workbook = new XSSFWorkbook(fis);
			policyDetailsSheet = workbook.getSheet("policy_fund_details");
			irPolicyDetailsSheet = workbook.getSheet("irpolicy_fund_details");
			if (irPolicyDetailsSheet == null)
				throw new Exception("IR_policy_fund_details sheet is missing");
			if (policyDetailsSheet == null)
				throw new Exception("policy_fund_details sheet is missing");
			int totalPolicies = policyDetailsSheet.getLastRowNum();
			int totalIRPolicies = irPolicyDetailsSheet.getLastRowNum();
			policyFundsList = new ArrayList<PolicyFundsPojo>(totalPolicies);
			irPolicyFundsList = new ArrayList<PolicyFundsPojo>(totalIRPolicies);
			
			//Collecting total normal policies
			if (totalPolicies >= 1) {				
				for (int i = 1; i <= totalPolicies; i++) {					
				//	System.out.println(policyDetailsSheet.getRow(i).getCell(1)+"  "+policyDetailsSheet.getRow(i).getCell(2)+"   "+policyDetailsSheet.getRow(i).getCell(3));
					PolicyFundsPojo policyFundsPojo = new PolicyFundsPojo();
					policyFundsPojo.setPolicyNumber(policyDetailsSheet.getRow(i).getCell(1).toString());
					policyFundsPojo.setSourceFunds(policyDetailsSheet.getRow(i).getCell(2).toString());
					policyFundsPojo.setTargetFund(policyDetailsSheet.getRow(i).getCell(3).toString());
					policyFundsList.add(policyFundsPojo);
				}	
				
				policyMap.put("normalPolicies", policyFundsList);
			}
			
			//Collecting total IR policies
			if (totalIRPolicies >= 1) {				
				for (int i = 1; i <= totalIRPolicies; i++) {					
				//	System.out.println(irPolicyDetailsSheet.getRow(i).getCell(1)+"  "+irPolicyDetailsSheet.getRow(i).getCell(2)+"   "+irPolicyDetailsSheet.getRow(i).getCell(3));
					PolicyFundsPojo policyFundsPojo = new PolicyFundsPojo();
					policyFundsPojo.setPolicyNumber(irPolicyDetailsSheet.getRow(i).getCell(1).toString());
					policyFundsPojo.setSourceFunds(irPolicyDetailsSheet.getRow(i).getCell(2).toString());
					policyFundsPojo.setTargetFund(irPolicyDetailsSheet.getRow(i).getCell(3).toString());
					irPolicyFundsList.add(policyFundsPojo);
				}	
				policyMap.put("irPolicies", irPolicyFundsList);
			}
		} catch (FileNotFoundException fileNotFoundException) {
			System.out.println("FileNotFoundException	 :" + fileNotFoundException.getMessage());
		} catch (IOException ioException) {
			System.out.println("IOException :" + ioException.getMessage());
		} catch (Exception exception) {
			System.out.println("Exception :" + exception.getMessage());
		}
		
		return policyMap;
	}	
}
