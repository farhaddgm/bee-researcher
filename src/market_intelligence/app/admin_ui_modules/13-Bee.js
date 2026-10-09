
    // Bee Researcher branding is kept in one place so both the login card and
    // the collapsible sidebar use the supplied artwork without a text fallback.
    (function(){
      const loginLogo=document.querySelector('#login .logo');
      if(loginLogo)loginLogo.innerHTML='<img class="brand-logo" src="/assets/bee-researcher-grey.svg" alt="Bee Researcher">';
      const sidebarLogo=document.querySelector('#sidebar .logo');
      if(sidebarLogo)sidebarLogo.innerHTML='<img class="brand-logo-full" src="/assets/bee-researcher-grey.svg" alt="Bee Researcher"><img class="brand-logo-mark" src="/assets/bee.svg" alt="Bee Researcher">';
    })();
