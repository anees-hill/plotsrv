import time

### PART 1
# matplotib/seaborn
from plotsrv.server import start_plot_server, stop_plot_server, refresh_plot_server
import matplotlib.pyplot as plt
import seaborn as sns
start_plot_server()
dat = sns.load_dataset('titanic') 
sns.scatterplot(data=dat, x="age", y="fare")
plt.show()
print('plot 1 (matplotlib) up')
time.sleep(10)
stop_plot_server()

### PART 2
# plotnine
from plotnine import *
start_plot_server() 
p=(ggplot(dat, aes("age", "fare")) + geom_point()) 
refresh_plot_server(p)
print('plot 2 (plotnine) up')
time.sleep(10) 

stop_plot_server()
print('script finished')
