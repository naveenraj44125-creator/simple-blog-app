"""
Base configurator class for application-specific configurations.
"""

class BaseConfigurator:
    """Base class for all application configurators"""
    
    def __init__(self, client, config):
        """
        Initialize configurator
        
        Args:
            client: LightsailBase client instance
            config: DeploymentConfig instance
        """
        self.client = client
        self.config = config
    
    def configure(self) -> bool:
        """
        Configure the application/service.
        Must be implemented by subclasses.
        
        Returns:
            bool: True if configuration succeeded, False otherwise
        """
        raise NotImplementedError("Subclasses must implement configure()")
    
    def get_name(self) -> str:
        """Get the name of this configurator"""
        return self.__class__.__name__.replace('Configurator', '')
