package com.navisys;

import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;

import javax.servlet.Filter;
import javax.servlet.FilterChain;
import javax.servlet.FilterConfig;
import javax.servlet.ServletException;
import javax.servlet.ServletRequest;
import javax.servlet.ServletResponse;
import javax.servlet.http.Cookie;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

public class ServletFilter implements Filter {


	private FileWriter accessLogFile=null;



	@Override
	public void destroy() {
	}


	@Override
	public void doFilter(ServletRequest request, ServletResponse response,FilterChain chain) throws IOException, ServletException {
		//SCR 45494:Start
		double startTime=System.currentTimeMillis();

		//chain.doFilter(request, response);
		HttpServletRequest hReq=(HttpServletRequest) request;
		HttpServletResponse hRes=(HttpServletResponse) response;
		if ( acceptsGZipEncoding(hReq) ) {
			hRes.addHeader("Content-Encoding", "gzip");
		      GZipServletResponseWrapper gzipResponse =
		        new GZipServletResponseWrapper(hRes);
		      chain.doFilter(request, gzipResponse);
		      gzipResponse.close();
		    } else {
		      chain.doFilter(request, response);
		    }

		double endTime=System.currentTimeMillis();
		double deltaTime=(endTime-startTime)/1000;
		//SCR 45494:End
		
		String remoteAddress=hReq.getRemoteAddr();
		SimpleDateFormat dateFormat=new SimpleDateFormat("[dd/MMM/yyyy:HH:mm:ss]");
		String endDate=dateFormat.format(new Date());

		StringBuffer sb=new StringBuffer();
		sb.append(remoteAddress);
		sb.append(" - - ");
		sb.append(endDate);
		sb.append(' ');
		sb.append(deltaTime);
		sb.append(" \"");
		sb.append(hReq.getMethod());
		sb.append(' ');
		sb.append(hReq.getRequestURI());
		sb.append(" HTTP/1.1\" ");

		sb.append('"');
		sb.append(hReq.getHeader("user-agent"));
		sb.append('"');

		String jSessionId=null;
		String userId=null;
		Cookie cookie1[]= hReq.getCookies();
		if (cookie1 != null) 
		{                                            
			for (int i=0; i<cookie1.length; i++) 
			{                         
				Cookie cookie = cookie1[i];                                 

				if (cookie != null && cookie.getName().equals("JSESSIONID"))
					jSessionId = cookie.getValue();                          

				if (cookie != null && cookie.getName().equals("USERID"))    
					userId = cookie.getValue();                              
			}                                                              

			if (userId != null) sb.append(" USERID="+userId);              
			if (jSessionId !=null) sb.append(" JSESSIONID="+jSessionId);   
		}                                                                 
		sb.append("\n");                                                  

		String completeURL = hReq.getRequestURL().append(hReq.getQueryString() != null ? "?" + hReq.getQueryString(): "").toString();
		//System.out.println("visiting ..." + completeURL);
		//SCR 55813
		sb.append("Troubleshooting Timeout:").append(completeURL).append("\n");
		//SCR 55813 
		accessLogFile.write(sb.toString());                               
		accessLogFile.flush();                                            
	}
	@Override
	public void init(FilterConfig filterConfig) throws ServletException {

		try {
			this.accessLogFile=new FileWriter(filterConfig.getInitParameter("access.log.path"));
		} catch (IOException e) {
			e.printStackTrace(System.err);
			throw new ServletException(e);
		}

	}
	
	 private boolean acceptsGZipEncoding(HttpServletRequest httpRequest) {
	      String acceptEncoding = 
	        httpRequest.getHeader("Accept-Encoding");

	      return acceptEncoding != null && 
	             acceptEncoding.indexOf("gzip") != -1;
	  }

}
